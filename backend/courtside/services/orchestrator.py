"""Orchestrator: coordinates the data, prediction, analysis and grading agents.
Every step is logged in `analysis_runs` and `audit_log`. Failures in optional steps
(e.g. odds feed) are recorded and the run continues with what is verified."""
from __future__ import annotations

import datetime as dt
import logging
import traceback

from sqlalchemy import select

from ..config import get_settings
from ..db import session_scope
from ..models import AnalysisRun, Game, ModelVersion, Player, Prediction, audit, utcnow
from ..modeling.baseline import MARKET_LABELS
from ..odds_math import decimal_to_american  # noqa: F401  (re-export convenience)
from ..providers.espn import ESPNClient, ProviderError
from .analysis import analyze_day
from .grading import grade_games
from .ingest import ingest_box_scores, ingest_injuries, ingest_odds_api, ingest_schedule, today_et
from .learning import production_model
from .notify import notify

log = logging.getLogger(__name__)


def _fmt_price(p: int) -> str:
    return f"+{p}" if p > 0 else str(p)


def run_analysis(day: dt.date | None = None, run_type: str = "manual", fetch_odds: bool = True,
                 odds_game_ids: list[str] | None = None) -> dict:
    day = day or today_et()
    st = get_settings()
    espn = ESPNClient()
    with session_scope() as s:
        run = AnalysisRun(run_type=run_type, target_date=day)
        s.add(run)
        s.flush()
        run_id = run.id
        audit(s, "orchestrator", "run_started", run_id=run_id, run_type=run_type, date=day)
    summary: dict = {"run_id": run_id, "date": str(day), "steps": {}}
    try:
        with session_scope() as s:
            games = ingest_schedule(s, day, espn)
            summary["steps"]["schedule"] = len(games)
            # make sure recent results are in before projecting
            recent = s.execute(select(Game).where(Game.game_date >= day - dt.timedelta(days=4),
                                                  Game.game_date < day, Game.box_loaded.is_(False))).scalars().all()
            for d in sorted({g.game_date for g in recent}):
                ingest_schedule(s, d, espn)
            summary["steps"]["box_scores"] = ingest_box_scores(s, recent, espn)
        with session_scope() as s:
            try:
                summary["steps"]["injuries"] = ingest_injuries(s, espn)
            except ProviderError as e:
                summary["steps"]["injuries"] = f"error: {e}"
        kind = run_type.split("_")[0]  # pregame_60 -> pregame
        scheduled = {"morning", "afternoon", "pregame", "pretip"}
        allowed = {r.strip() for r in st.odds_fetch_runs.split(",") if r.strip()}
        if kind in scheduled and kind not in allowed:
            fetch_odds = False
        if fetch_odds and st.odds_api_key:
            try:
                with session_scope() as s:
                    summary["steps"]["odds"] = res_odds = ingest_odds_api(s, day, only_game_ids=odds_game_ids)
                    if res_odds.get("skipped_budget"):
                        notify(s, f"odds-budget-{day}", "ops", "Odds API credit reserve reached",
                               f"Skipped odds for {res_odds['skipped_budget']} game(s) on {day} to stay above "
                               f"ODDS_API_MIN_CREDITS={st.odds_api_min_credits}.")
                    if res_odds.get("failed_events"):
                        notify(s, f"odds-failed-{run_id}", "ops", "Odds feed failed for some games",
                               f"Run {run_id}: no odds for {res_odds['failed_events']} game(s) after retries. "
                               "Picks in those games were not re-priced.")
            except ProviderError as e:
                summary["steps"]["odds"] = f"error: {e}"
                with session_scope() as s:
                    notify(s, f"odds-failed-{run_id}", "ops", "Odds feed failed",
                           f"Run {run_id}: odds could not be refreshed ({e}).")
        else:
            summary["steps"]["odds"] = "skipped (no ODDS_API_KEY or disabled) — using stored/manual odds"

        with session_scope() as s:
            run = s.get(AnalysisRun, run_id)
            mv = production_model(s)
            publish = mv is not None
            if mv is None:
                mv = s.execute(select(ModelVersion).order_by(ModelVersion.created_at.desc())).scalars().first()
                summary["warning"] = ("no approved production model — analysis is paper-only, nothing published"
                                      if mv else "no model registered — run `courtside train` first")
            if mv is None:
                raise RuntimeError(summary["warning"])
            res = analyze_day(s, day, run, mv, publish=publish)
            summary["model_version"] = f"{mv.name} {mv.version} ({mv.status})"
            _notify_run(s, res, run_id)
            summary["analysis"] = {k: v for k, v in res.items() if not k.startswith("_")}
            run.status, run.finished_at, run.summary = "ok", utcnow(), summary
    except Exception as e:  # report, never hide
        log.exception("analysis run failed")
        with session_scope() as s:
            run = s.get(AnalysisRun, run_id)
            run.status, run.finished_at, run.error = "error", utcnow(), traceback.format_exc()[-4000:]
            run.summary = summary
            audit(s, "orchestrator", "run_failed", run_id=run_id, error=str(e))
            notify(s, f"run-failed-{run_id}", "ops", "Analysis run failed", f"Run {run_id} ({run_type}): {e}")
        summary["error"] = str(e)
    return summary


def _notify_run(s, res: dict, run_id: int) -> None:
    for pid in res.get("_publish_ids", []):
        p = s.get(Prediction, pid)
        player = s.get(Player, p.player_id)
        key = f"pick-{p.game_id}-{p.player_id}-{p.market}-{p.side}-{p.line}-{p.book}-{p.price}"
        notify(s, key, "recommendation",
               f"{player.name} {p.side.upper()} {p.line} {MARKET_LABELS[p.market]}",
               f"{p.book} {_fmt_price(p.price)} | model {p.model_prob:.0%} | fair {_fmt_price(p.fair_odds)} | "
               f"EV {p.ev:+.1%} | odds as of {p.odds_fetched_at:%Y-%m-%d %H:%M} UTC | generated {p.created_at:%H:%M} UTC")
    withdrawn = [s.get(Prediction, pid) for pid in res.get("_withdrawn_ids", [])]
    if withdrawn:  # one message per run, however many picks are affected
        lines = [f"{s.get(Player, p.player_id).name} {p.side} {p.line:g} {MARKET_LABELS[p.market]}" for p in withdrawn]
        notify(s, f"withdrawn-run-{run_id}", "withdrawal", f"WITHDRAWN: {len(withdrawn)} pick(s)",
               f"No longer meet eligibility filters as of run {run_id}:\n" + "\n".join(lines))


def run_grading(day: dt.date | None = None) -> dict:
    days = [day] if day else [today_et() - dt.timedelta(days=1), today_et()]
    espn = ESPNClient()
    out = {}
    with session_scope() as s:
        run = AnalysisRun(run_type="grading", target_date=days[-1])
        s.add(run)
        s.flush()
        for d in days:
            games = ingest_schedule(s, d, espn)
            box = ingest_box_scores(s, games, espn)
            out[str(d)] = {"box_scores": box, "grading": grade_games(s, games)}
        run.status, run.finished_at, run.summary = "ok", utcnow(), out
        settled = sum(v["grading"]["settled"] for v in out.values())
        if settled:
            notify(s, f"graded-{days[-1]}-{settled}", "results", f"Graded {settled} predictions",
                   ", ".join(f"{d}: {v['grading']}" for d, v in out.items()))
    return out
