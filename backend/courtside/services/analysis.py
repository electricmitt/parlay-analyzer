"""Player prop analysis engine: projections -> probabilities -> EV -> eligibility.

All arithmetic is deterministic. Eligibility filters are explicit, configurable and
reported per prop (`reasons`) so every PASS is explainable.
"""
from __future__ import annotations

import datetime as dt
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    AnalysisRun, Game, ModelVersion, OddsSnapshot, Prediction, PredictionEvent, Projection, audit, utcnow,
)
from ..modeling.baseline import MARKET_LABELS, MARKETS, BaselineParams, build_features, prob_over_under, simulate, summarize
from ..modeling import calibration as cal
from ..modeling.data import load_history
from ..odds_math import (
    expected_value_with_push, implied_prob, kelly_fraction, no_vig_two_way, prob_to_american,
)
from .ingest import injuries_fresh, latest_injuries, latest_odds, team_roster

BLOCKING_INJURY = {"out", "doubtful", "suspension", "suspended"}
UNCERTAIN_INJURY = {"questionable", "day-to-day", "game time decision", "gtd"}


@dataclass
class PropEval:
    snapshot: OddsSnapshot
    side: str
    price: int
    p_win: float
    p_push: float
    ev: float
    implied: float
    novig: float | None
    consensus: float | None
    fair: int
    kelly_units: float
    eligible: bool
    reasons: list[str] = field(default_factory=list)
    factors: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    data_quality: dict = field(default_factory=dict)


def _side_price(snap: OddsSnapshot, side: str) -> int | None:
    return snap.over_price if side == "over" else snap.under_price


def consensus_novig(snaps: list[OddsSnapshot]) -> dict[tuple, float]:
    """(game, player, market, line) -> median no-vig P(over) across books quoting both sides."""
    acc: dict[tuple, list[float]] = defaultdict(list)
    for sn in snaps:
        if sn.over_price is not None and sn.under_price is not None:
            acc[(sn.game_id, sn.player_id, sn.market, sn.line)].append(no_vig_two_way(sn.over_price, sn.under_price)[0])
    return {k: statistics.median(v) for k, v in acc.items()}


def blend_with_market(p_model: float, p_market: float, weight: float) -> float:
    """Move from the market toward the model by `weight`, in log-odds (1.0 = model, 0.0 = market)."""
    def logit(p: float) -> float:
        p = min(max(p, 1e-6), 1 - 1e-6)
        return math.log(p / (1 - p))
    x = logit(p_market) + weight * (logit(p_model) - logit(p_market))
    return 1 / (1 + math.exp(-x))


def evaluate_prop(snap: OddsSnapshot, side: str, p_over: float, p_under: float, p_push: float,
                  consensus_over: float | None, ctx: dict) -> PropEval | None:
    st = get_settings()
    price = _side_price(snap, side)
    if price is None:
        return None
    raw_win = p_over if side == "over" else p_under
    novig = None
    if snap.over_price is not None and snap.under_price is not None:
        nv_o, nv_u = no_vig_two_way(snap.over_price, snap.under_price)
        novig = nv_o if side == "over" else nv_u
    cons = None if consensus_over is None else (consensus_over if side == "over" else 1 - consensus_over)
    # p_win excludes pushes; compare to the market on the same conditional basis
    raw_cond = raw_win / max(1e-9, 1 - p_push)
    market_ref = cons if cons is not None else novig
    reasons: list[str] = []
    w = st.market_blend_weight
    p_win, p_cond, blend_info = raw_win, raw_cond, {}
    if w < 1:
        if market_ref is None:
            reasons.append("no two-sided market price to anchor the estimate")
        else:
            p_cond = blend_with_market(raw_cond, market_ref, w)
            p_win = p_cond * (1 - p_push)
            blend_info = {"market_blend": {
                "weight": w, "raw_model_prob": round(raw_win, 4), "market_prob": round(market_ref, 4),
                "raw_model_ev": round(expected_value_with_push(raw_win, p_push, price), 4)}}
    ev = expected_value_with_push(p_win, p_push, price)
    if ev < st.min_ev:
        reasons.append(f"EV {ev:+.1%} below minimum {st.min_ev:.0%}")
    if not (st.min_prob <= p_win <= st.max_prob):
        reasons.append(f"win probability {p_win:.0%} outside [{st.min_prob:.0%}, {st.max_prob:.0%}]")
    if market_ref is not None and abs(raw_cond - market_ref) > st.max_model_market_gap:
        reasons.append(f"model ({raw_cond:.0%}) disagrees with no-vig market ({market_ref:.0%}) by more than "
                       f"{st.max_model_market_gap:.0%} — likely missing information")
    age_min = (utcnow() - snap.fetched_at).total_seconds() / 60
    if age_min > st.max_odds_age_min:
        reasons.append(f"odds are {age_min:.0f} min old (max {st.max_odds_age_min})")
    reasons.extend(ctx["player_reasons"])
    kelly = 0.0
    if not reasons:
        kelly = min(kelly_fraction(p_cond, price) * st.kelly_fraction, st.max_stake_pct) * st.bankroll_units
    return PropEval(
        snapshot=snap, side=side, price=price, p_win=p_win, p_push=p_push, ev=ev, implied=implied_prob(price),
        novig=novig, consensus=cons, fair=prob_to_american(p_cond), kelly_units=round(kelly, 2),
        eligible=not reasons, reasons=reasons,
        factors=list(ctx["factors"]) + ([f"Provisional blend: {w:.0%} model ({raw_cond:.0%}) with {1 - w:.0%} "
                                         f"no-vig market ({market_ref:.0%}) = {p_cond:.0%}"] if blend_info else []),
        risks=list(ctx["risks"]),
        data_quality={**ctx["data_quality"], **blend_info, "odds_age_min": round(age_min, 1), "odds_source": snap.source},
    )


def calibrated_over(params: BaselineParams, market: str, p_raw: float, row) -> tuple[float, bool]:
    early = float(row.get("n_current_season", 99) or 0) < params.new_season_games
    playoff = bool(row.get("is_playoff", False))
    model = (params.calibration or {}).get(market)
    return float(cal.apply(model, p_raw, float(playoff), float(early))[0]), early


def player_context(row: pd.Series, game: Game, injury, injuries_ok: bool, market: str) -> dict:
    st = get_settings()
    reasons, factors, risks = [], [], []
    n = int(row.get("n_games", 0) or 0)
    if n < st.min_games_history:
        reasons.append(f"only {n} games of history (min {st.min_games_history})")
    if not injuries_ok:
        reasons.append("injury report is stale or unavailable — availability unverified")
    status = (injury.status if injury else "").lower()
    if status in BLOCKING_INJURY:
        reasons.append(f"listed {injury.status} on injury report")
    elif status in UNCERTAIN_INJURY or status.startswith("questionable"):
        reasons.append(f"availability uncertain ({injury.status})")
    mu, sd = float(row["mu_min"]), float(row["sd_min"])
    cv = sd / max(mu, 1)
    if cv > st.max_minutes_cv:
        reasons.append(f"minutes projection too uncertain (CV {cv:.2f} > {st.max_minutes_cv})")
    dsl = row.get("days_since_last")
    if dsl is not None and dsl > 10 and dsl < 90:
        reasons.append(f"has not played in {int(dsl)} days — role unverified")
    team_id = game.home_team_id if row["team_id"] == game.home_team_id else game.away_team_id
    if row.get("last_team_id") and row["last_team_id"] != team_id:
        reasons.append("player's most recent game was for a different team")

    factors.append(f"Projected {mu:.1f} min (last-5 avg {row['last5_min']:.1f}, sd {sd:.1f})")
    comps = {"pra": ["pts", "reb", "ast"], "pr": ["pts", "reb"], "pa": ["pts", "ast"], "ra": ["reb", "ast"]}.get(market, [market])
    for c in comps:
        opp = float(row.get(f"opp_{c}", 1.0) or 1.0)
        if abs(opp - 1) >= 0.03:
            word = "allows" if opp > 1 else "suppresses"
            factors.append(f"Opponent {word} {MARKET_LABELS[c].lower()} ({(opp - 1):+.0%} vs league)")
        factors.append(f"{MARKET_LABELS[c]}: L5 {row[f'l5_{c}']:.1f}, L10 {row[f'l10_{c}']:.1f}, "
                       f"season {row[f'season_{c}']:.1f}")
    if row.get("is_playoff"):
        po = [float(row.get(f"po_{c}", 1.0) or 1.0) for c in comps]
        factors.append(f"Playoff adjustment to per-minute production: {', '.join(f'x{x:.2f}' for x in po)}")
    if dsl == 1:
        risks.append("Second night of a back-to-back")
    if cv > 0.2:
        risks.append(f"Volatile minutes (sd {sd:.1f})")
    risks.append("Blowout risk can cut minutes (not yet modelled — Phase 2)")
    risks.append("Teammate absences / usage redistribution not yet modelled (Phase 2)")
    if status and status not in BLOCKING_INJURY:
        risks.append(f"Injury report: {injury.status} — {injury.detail or ''}".strip(" —"))
    return {"player_reasons": reasons, "factors": factors, "risks": risks,
            "data_quality": {"n_games": n, "days_since_last": None if dsl is None else int(dsl),
                             "injury_status": injury.status if injury else "not listed",
                             "injury_report_fresh": injuries_ok, "stats_source": "espn"}}


def analyze_day(s: Session, day: dt.date, run: AnalysisRun, mv: ModelVersion, publish: bool = True) -> dict:
    st = get_settings()
    now = utcnow()
    games = [g for g in s.execute(select(Game).where(Game.game_date == day)).scalars()
             if g.start_time > now and g.status == "STATUS_SCHEDULED"]
    summary = {"games": len(games), "projections": 0, "props_evaluated": 0, "eligible": 0,
               "recommended": 0, "withdrawn": 0, "kept_unverified": 0, "pass_games": []}
    if not games:
        return summary
    params = BaselineParams.from_dict(mv.params)
    hist = load_history(s, before=day, since=day - dt.timedelta(days=params.lookback_days + 5))
    injuries = latest_injuries(s)
    inj_ok = injuries_fresh(s)

    targets = []
    for g in games:
        for team_id, opp_id in ((g.home_team_id, g.away_team_id), (g.away_team_id, g.home_team_id)):
            for pid in team_roster(s, team_id, day):
                targets.append({"player_id": pid, "game_date": day, "opponent_id": opp_id, "team_id": team_id,
                                "game_id": g.id, "season_type": g.season_type})
    feats = build_features(hist, pd.DataFrame(targets), params)
    feats = feats[feats["n_games"] > 0].copy()
    sims: dict[tuple[str, str], dict] = {}
    for _, row in feats.iterrows():
        inj = injuries.get(row["player_id"])
        if inj and inj.status.lower() in BLOCKING_INJURY:
            continue  # do not project players ruled out
        draws = simulate(row, params, n=st.n_sims, seed=st.random_seed + int(row["player_id"]) % 10_000)
        sims[(row["game_id"], row["player_id"])] = {"row": row, "draws": draws, "injury": inj}
        s.add(Projection(run_id=run.id, game_id=row["game_id"], player_id=row["player_id"], model_version_id=mv.id,
                         proj_minutes=float(row["mu_min"]), sd_minutes=float(row["sd_min"]),
                         injury_status=inj.status if inj else None, n_games=int(row["n_games"]),
                         markets={m: summarize(draws[m]) for m in MARKETS},
                         features=_jsonable_features(row)))
        summary["projections"] += 1

    game_ids = [g.id for g in games]
    snaps = [sn for sn in latest_odds(s, game_ids) if sn.market in MARKETS]
    cons = consensus_novig(snaps)
    # previous active predictions for these (not yet started) games get superseded/withdrawn
    prev_active = s.execute(select(Prediction).where(Prediction.game_id.in_(game_ids),
                                                     Prediction.status == "active")).scalars().all()
    games_by_id = {g.id: g for g in games}
    cands = []  # (snapshot, best side eval, sim, summary)
    for sn in snaps:
        key = (sn.game_id, sn.player_id)
        if key not in sims:
            continue
        sim = sims[key]
        draws = sim["draws"][sn.market]
        p_raw, _, p_push = prob_over_under(draws, sn.line)
        p_over, early = calibrated_over(params, sn.market, p_raw, sim["row"])
        p_under = max(0.0, 1.0 - p_over - p_push)
        ctx = player_context(sim["row"], games_by_id[sn.game_id], sim["injury"], inj_ok, sn.market)
        ctx = {**ctx, "factors": ctx["factors"] + [
            f"Calibrated P(over) {p_over:.0%} (raw simulation {p_raw:.0%}"
            f"{', playoff' if sim['row'].get('is_playoff') else ''}{', early season' if early else ''})"]}
        if params.validated_markets and sn.market not in params.validated_markets:
            ctx["player_reasons"] = ctx["player_reasons"] + [
                f"{MARKET_LABELS[sn.market]} market not validated by the model's backtest"]
        evals = [e for side in ("over", "under")
                 if (e := evaluate_prop(sn, side, p_over, p_under, p_push,
                                        cons.get((sn.game_id, sn.player_id, sn.market, sn.line)), ctx))]
        if evals:  # one prediction per (player, market, book): the better side
            cands.append((sn, max(evals, key=lambda e: e.ev), sim, summarize(draws)))

    # Publish: per (player, market, side) the best eligible book (ties -> preferred book).
    # Decided before insert because predictions are immutable once written.
    best_by_prop: dict[tuple, int] = {}
    for i, (sn, e, _, _) in enumerate(cands):
        if not e.eligible:
            continue
        k = (sn.game_id, sn.player_id, sn.market, e.side)
        j = best_by_prop.get(k)
        if j is None or (e.ev, sn.book == st.preferred_book) > (cands[j][1].ev, cands[j][0].book == st.preferred_book):
            best_by_prop[k] = i
    publish_idx = set(best_by_prop.values()) if publish else set()

    new_preds: list[Prediction] = []
    for i, (sn, best, sim, summ) in enumerate(cands):
        pub = i in publish_idx
        pred = Prediction(
            run_id=run.id, game_id=sn.game_id, player_id=sn.player_id, market=sn.market, side=best.side,
            line=sn.line, book=sn.book, price=best.price, odds_snapshot_id=sn.id, odds_fetched_at=sn.fetched_at,
            model_version_id=mv.id, created_at=now, proj_mean=summ["mean"], proj_p10=summ["p10"],
            proj_p50=summ["p50"], proj_p90=summ["p90"], proj_minutes=float(sim["row"]["mu_min"]),
            model_prob=best.p_win, implied_prob=best.implied, novig_prob=best.novig, consensus_prob=best.consensus,
            fair_odds=best.fair, ev=best.ev, kelly_stake=best.kelly_units, eligible=best.eligible,
            reasons=best.reasons, factors=best.factors, risks=best.risks, data_quality=best.data_quality,
            record_type="published" if pub else "paper", published=pub,
        )
        s.add(pred)
        new_preds.append(pred)
        summary["props_evaluated"] += 1
        summary["eligible"] += int(best.eligible)
    s.flush()
    for p in new_preds:
        s.add(PredictionEvent(prediction_id=p.id, event="published" if p.published else "created",
                              detail={"run_id": run.id}))

    # Old prices say nothing about a pick. Without fresh odds for its game it stays up, unverified,
    # unless the player's availability got worse: that is new information we do have.
    fresh_games = {sn.game_id for sn in snaps
                   if (utcnow() - sn.fetched_at).total_seconds() / 60 <= st.max_odds_age_min}

    def availability_ok(p: Prediction) -> bool:
        if (p.game_id, p.player_id) not in sims:
            return False
        inj = injuries.get(p.player_id)
        status = (inj.status if inj else "").lower()
        return status not in UNCERTAIN_INJURY and not status.startswith("questionable")

    for p in prev_active:
        if p.published and (p.game_id, p.player_id, p.market, p.side) not in best_by_prop:
            if p.game_id not in fresh_games and availability_ok(p):
                s.add(PredictionEvent(prediction_id=p.id, event="unverified",
                                      detail={"by_run": run.id, "reason": "odds could not be refreshed"}))
                summary["kept_unverified"] += 1
                continue
            p.status = "withdrawn"
            s.add(PredictionEvent(prediction_id=p.id, event="withdrawn",
                                  detail={"by_run": run.id, "reason": "no longer meets eligibility filters"}))
            summary["withdrawn"] += 1
            summary.setdefault("_withdrawn_ids", []).append(p.id)
        else:
            p.status = "superseded"
            s.add(PredictionEvent(prediction_id=p.id, event="superseded", detail={"by_run": run.id}))
    summary["recommended"] = len(best_by_prop)
    summary["_publish_ids"] = [p.id for p in new_preds if p.published]
    for g in games:
        if not any(k[0] == g.id for k in best_by_prop):
            summary["pass_games"].append(g.id)
    audit(s, "analysis_agent", "analyze_day", run_id=run.id, date=day,
          **{k: v for k, v in summary.items() if not k.startswith("_")})
    return summary


def _jsonable_features(row: pd.Series) -> dict:
    keep = {}
    for k, v in row.items():
        if k.startswith(("rate_", "opp_", "l5_", "l10_", "season_")) or k in (
                "mu_min", "sd_min", "n_games", "days_since_last", "last5_min", "season_min", "opp_games",
                "n_current_season", "is_playoff") or k.startswith("po_"):
            try:
                keep[k] = None if pd.isna(v) else float(v)
            except (TypeError, ValueError):
                continue
    return keep
