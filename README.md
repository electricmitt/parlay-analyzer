# Courtside AI — NBA player prop research engine

Courtside AI projects NBA player stat distributions and turns them into probabilities. It compares those
probabilities with sportsbook prices and recommends a prop only when it passes explicit, auditable filters.
Otherwise it says **PASS**.

> Research tool only. It never places wagers. Probabilities are model estimates with real uncertainty, and
> nothing here guarantees a winning outcome.

## What's in this repo (status as of Phase 1)

| Area | Status | Notes |
|---|---|---|
| NBA schedule, box scores, injury reports | **Implemented** | ESPN public JSON. Provenance-tagged, rate-limited, retried; failures logged, never guessed |
| Historical backfill | **Implemented** | `courtside backfill`; idempotent and re-runnable |
| Player projection model (baseline) | **Implemented** | Minutes × per-minute rate × opponent factor; negative-binomial Monte Carlo (20k sims) |
| Markets | **Implemented** | PTS, REB, AST, 3PM, STL, BLK, TOV, PRA, P+R, P+A, R+A (combos share the minutes draw) |
| Odds ingestion | **Implemented** | The Odds API (incl. Hard Rock Bet), plus manual entry in the dashboard |
| Probability / fair odds / no-vig / EV / ¼-Kelly analysis | **Implemented** | Deterministic, unit-tested |
| Eligibility filters + PASS | **Implemented** | Every rejected prop lists its reasons |
| Prediction storage | **Implemented** | Append-only. Analytic fields are frozen at insert (DB guard); lifecycle events logged |
| Automated grading | **Implemented** | Win/loss/push/void from official box scores; closing price captured; error tags |
| Daily scheduler (ET) | **Implemented** | 9:00, 13:00, T-60/T-15 per game, overnight grading, weekly evaluation |
| Walk-forward evaluation, model registry, champion/challenger gate, rollback | **Implemented** | Promotion requires passing the gate; challengers also need shadow testing |
| Dashboard | **Implemented** | Command Center, Game Analyzer, Player Research (with side-by-side compare), Odds Intelligence, Parlay Builder, Performance, Learning Center, Settings. Team logos and headshots load from ESPN's image CDN, with an initials fallback |
| Notifications | **Implemented (basic)** | Dashboard feed + Discord/Telegram webhooks, de-duplicated. Email/push are planned |
| Performance analytics | **Implemented** | Win rate, units, ROI vs expected ROI, drawdown, Brier vs market, calibration, CLV, breakdowns |
| Injury-driven usage redistribution, blowout model, minutes model | Planned (Phase 2) | Shown as explicit risks on every pick today |
| Probability recalibration (isotonic), ensembles, GBMs | Planned (Phase 2) | Adopt only if walk-forward shows gains |
| Parlay builder | **Experimental** | Read-only estimate: Gaussian copula with shrunk same-game correlations from historical residuals. Not walk-forward validated, never published. EV is withheld for same-game or mixed-book parlays until you enter the book's quoted price |
| Courtside Intelligence assistant | **Implemented (rule-based)** | Answers a fixed set of question types from the app's own API. No language model, so it cannot answer freeform questions |
| Joint game simulation (shared minutes, pace, blowout state), parlay recommendations | Planned (Phase 3) | Would replace the experimental estimate and needs walk-forward validation first |
| Drift detection, automated retraining promotion | Planned (Phase 4) | Weekly candidate registration already exists |
| Event-driven updates, provider failover, monitoring | Planned (Phase 5) | |
| Screenshot odds extraction | Planned | Will always require human confirmation |

## Architecture

```
               ┌──────────── scheduler (APScheduler, America/New_York) ────────────┐
               │ 09:00 morning · 13:00 afternoon · T-60/T-15 pregame · grading     │
               └──────────────────────────────┬─────────────────────────────────────┘
                                              ▼
 ESPN JSON ──► Data agent (ingest.py) ──► SQL DB ◄── Odds agent (The Odds API / manual)
                                              │
                         Prediction agent (modeling/baseline.py: features as-of D, MC sim)
                                              │
                    Prop analysis (services/analysis.py: EV, no-vig, filters, PASS)
                                              │
                    Orchestrator (run log, audit log, notifications, publish/withdraw)
                                              │
                    Grading + learning (grading.py, learning.py, evaluate.py)
                                              │
                         FastAPI (api.py) ──► Next.js dashboard (frontend/)
```

* **Smallest reliable stack.** Python 3.11+, FastAPI, SQLAlchemy + Alembic, and SQLite by default
  (switch to Postgres with one env var). APScheduler runs in a single worker process, and the frontend is
  Next.js + Tailwind + Recharts. Redis, Celery, MLflow and Optuna were left out on purpose. They earn their
  place only once there are several workers or models to tune; the model registry lives in the
  `model_versions` table for now.
* **No LLM in the loop yet.** Every number comes from deterministic code. Explanations are generated from
  the model's actual features ("Opponent allows +6% points vs league"), not written freely.

### Data sources

| Source | Used for | Access | Cost | Limitations |
|---|---|---|---|---|
| ESPN site API (`site.api.espn.com`) | schedule, scores, box scores, injuries | public JSON, no key | free | Undocumented and can change without notice. Occasional malformed rows are skipped and logged. No lineups or tracking data |
| The Odds API | player prop prices (Hard Rock Bet = `hardrockbet`/`hardrockbet_fl`, DraftKings, FanDuel, BetMGM, Caesars = `williamhill_us`) | API key | free 500 credits/mo; $30/mo for 20k | Each request costs `markets × ceil(books/10)` credits per game. No historical prop archive on low tiers |
| Manual entry | any book, including Hard Rock Bet | dashboard form | free | Human error; both sides are needed for no-vig |

Not used: `stats.nba.com` and `cdn.nba.com`. They block non-browser clients, and Courtside does not spoof
browser headers to get around that. Licensed alternatives include Sportradar, SportsDataIO and BALLDONTLIE's
paid tiers. Those are the upgrade path if ESPN proves unreliable; the provider layer is one module per source.

## The model (baseline v1)

For player *i* in a game on date *D* (only rows with `game_date < D` are visible):

* **Minutes** ~ Normal(μ, σ), truncated to [0, 48]. μ is the EWMA of recent minutes (half-life 4 games),
  and σ is the exponentially weighted SD (floor 2.5).
* **Rate per minute** is the minutes-weighted EWMA (half-life 12), shrunk toward a position prior with 150
  prior minutes.
* **Opponent factor** is the opponent's last-20 stat allowed per game ÷ league average over the last 60 days.
  It is shrunk with 15 games of prior weight and clipped to ±12%. This captures both defense and pace.
* **Outcome**: stat | minutes ~ NegBin(mean = minutes × rate × opp, r). The dispersion *r* per stat is fitted
  by method of moments on prior residuals given actual minutes, so minutes noise isn't double counted.
* **Combo markets** sum component draws that share one minutes draw. That captures the main source of
  correlation; residual within-player correlation is a Phase 2 item.

`build_features` is the single code path for both backtest and live use. A test poisons all future rows and
asserts that the features don't change (no leakage).

### Eligibility filters (all must pass to publish)

* EV ≥ `MIN_EV` (3%) at the posted price, where pushes are counted as stake returned.
* Model probability within [30%, 85%].
* |model − no-vig market probability| ≤ 15 pts. When the model wildly disagrees with a liquid market, the
  usual cause is information the model doesn't have. These props are rejected, not celebrated.
* Odds no older than 45 minutes.
* At least 8 games of history; played within the last 10 days; same team as in the last game.
* A fresh injury report exists and the player is not Out, Doubtful, Questionable or Day-To-Day.
* Minutes CV ≤ 0.35.
* An approved **production** model exists. Without one, analysis runs paper-only.

These thresholds are initial defaults. Change them only on walk-forward evidence.

### Validation gate

`courtside train` runs a walk-forward backtest that refits every 14 days on prior data only. No historical
prop prices are freely available, so the backtest scores the probability distribution on **proxy lines**:
floor(last-10 average) + 0.5. It compares against a naive smoothed last-10 hit-rate baseline using Brier,
log loss, ECE, MAE and 80% interval coverage.

A first model is promoted only if all of these hold:

1. Points Brier improvement has a 95% CI below zero.
2. No market is significantly worse than the naive baseline.
3. ECE ≤ 0.04 in every market.

A challenger must significantly beat the champion on the same unseen window, and must be confirmed as
shadow-tested, before it can be promoted. The backtest measures *forecast quality, not profitability*. The
only honest profitability evidence is the live record graded against the prices that were actually available.

### Current results

**Production model: `baseline_ewma_nb 1.3.0`**, which adds a playoff factor and walk-forward Platt calibration.
It was promoted under a rule committed *before* the fresh test ran: promote only if v1.3 passes the unchanged
gate on a window never used during development.

* **Fresh test:** 2024-10-22 → 2025-06-22 (season start + full playoffs), 20,890 player-games per market.
  The calibrator was trained only on earlier predictions (burn-in from 2024-04).

| Market | Brier model / naive | ΔBrier 95% CI | ECE (v1.2 → v1.3) | 80% PI coverage |
|---|---|---|---|---|
| PTS | 0.2431 / 0.2550 | [−0.014, −0.010] | 0.035 → 0.011 | 77.7% |
| REB | 0.2374 / 0.2510 | [−0.015, −0.012] | 0.011 → 0.003 | 86.1% |
| AST | 0.2349 / 0.2474 | [−0.014, −0.011] | 0.016 → 0.005 | 90.4% |
| 3PM | 0.2162 / 0.2244 | [−0.010, −0.006] | 0.013 → 0.025 | 92.9% |
| PRA | 0.2432 / 0.2550 | [−0.013, −0.010] | 0.032 → 0.004 | 76.9% |

Caveats:

* v1.2 also passes on this window. The 2026 dev window, used for development and evaluated 5 times, is
  harder. v1.3's gain is mainly calibration; accuracy barely changes.
* Points and PRA intervals are slightly narrow. Pricing uses the calibrated probabilities, not the intervals.
* Only PTS, REB, AST, 3PM and PRA are validated. Props in other markets are analysed but never published.
* This measures forecast quality on proxy lines, not profit against real prices. The live graded record is the
  real test.

## Record types — never mixed

* `backtest`: walk-forward metrics stored on the model version (proxy lines, no prices).
* `paper`: every evaluated prop, at the price available when it was generated.
* `published`: the final pre-tip version of each recommendation. Superseded versions and withdrawn picks are
  tracked separately.
* `real_money`: bets you manually confirm via `POST /api/bets`.

## Quick start (local)

```bash
# backend
cd backend
python3 -m venv .venv && . .venv/bin/activate     # or: uv venv && uv pip install -e ".[dev]"
pip install -e ".[dev]"
cp .env.example .env                              # add ODDS_API_KEY if you have one
courtside migrate                                 # alembic upgrade head
courtside backfill --start 2025-10-21             # ~25 min: last season + this season to date
courtside train                                   # walk-forward eval, registers a candidate model
#   review the gate result; then promote via the Learning Center (or add --promote)
courtside serve                                   # API on :8000
courtside worker                                  # (separate shell) daily autonomous schedule

# frontend
cd ../frontend
cp .env.example .env.local
npm install && npm run dev                        # http://localhost:3000
```

One-off commands: `courtside analyze [--date YYYY-MM-DD] [--no-odds]` and `courtside grade [--date ...]`.

Tests: `cd backend && pytest` (all tests use synthetic data in temporary databases).

## Telegram digests

You get two messages each day:

* **Morning digest (9:00 AM ET):** the slate, every published pick, and yesterday's results.
* **Pre-tip digest (~30 min before the first game, `PRETIP_DIGEST_MINUTES`):** a fresh analysis first, with
  new picks flagged and withdrawn picks called out.

Each pick shows book, price, model probability, fair odds, EV, projection range, tip time, and when the odds
were captured. When nothing qualifies, the digest says PASS.

Setup:

1. In Telegram, message **@BotFather**, send `/newbot`, and copy the token into `backend/.env` as
   `TELEGRAM_BOT_TOKEN=...`.
2. Send any message to your new bot, then run `courtside telegram-setup`. It prints your chat id.
3. Put the chat id in `backend/.env` as `TELEGRAM_CHAT_ID=...` and run `courtside telegram-setup` again.
   It sends a test message.
4. Preview with `courtside digest --kind morning`. Send now with `courtside digest --kind morning --send`
   (add `--force` to resend).
5. Keep the scheduler running, using one of these:
   * **Mac:** install `deploy/com.courtside.worker.plist` as a LaunchAgent (the commands are in the file).
     The Mac must be awake at 9 AM and before tip-off.
   * **Server (recommended):** run `docker compose up -d worker` on a small always-on VPS.

Picks need prices. Without `ODDS_API_KEY` or manual entries, digests honestly report that there was nothing
to evaluate.

## Deployment

`docker compose up -d` runs Postgres, the API, the scheduler worker and the dashboard on a single host.
Run `docker compose exec api courtside backfill --start 2025-10-21` once, then `courtside train`.

### Realistic monthly cost

| Item | Option | $/month |
|---|---|---|
| Server (API + worker + Postgres/SQLite) | 2 vCPU / 4 GB VPS (Hetzner CX22, DigitalOcean basic) | 5–12 |
| Dashboard | Same VPS, or Vercel Hobby (personal use) | 0 |
| Stats data | ESPN public JSON | 0 |
| Odds | The Odds API free tier: about one points-only refresh per slate per day | 0 |
| Odds (recommended) | The Odds API 20k plan: 2–3 markets × 4 refreshes × full slate | 30 |
| Notifications | Discord / Telegram | 0 |
| **Total** | | **≈ $5 (manual odds) to ≈ $40 (automated odds)** |

Odds credit math: a 10-game slate × 1 market × 1 region-equivalent (≤10 books) = 10 credits per refresh.
`ODDS_FETCH_RUNS` controls which scheduled runs pull odds. With all four (`morning,afternoon,pregame,pretip`)
that is about 5 credits per game per day, roughly 1,100 per month, which needs a paid plan. The free-tier
setting `morning,pretip` is 2 credits per game per day (about 450 per month). Runs not listed are not
scheduled at all, because re-checking picks against old prices would only withdraw them as stale.
`ODDS_API_MIN_CREDITS` is a floor: when the balance reaches it, odds pulls stop and an ops alert is sent.

## Responsible use

Positive EV is a long-run statement about prices, not a prediction that any given bet wins; even a genuine
3–5% edge loses frequently and can run through long losing streaks. The staking figure shown is a capped
quarter-Kelly *analysis* (≤1% of bankroll). If gambling stops being fun: 1-800-GAMBLER.
