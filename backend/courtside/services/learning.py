"""Model registry, champion/challenger gate, rollback and post-game error attribution."""
from __future__ import annotations

import datetime as dt
import logging

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ModelVersion, audit, utcnow
from ..modeling.baseline import BaselineParams
from ..modeling.data import load_history
from ..modeling.evaluate import (
    EVAL_MARKETS, calibrate_walk_forward, fit_final_calibration, fit_params, paired_bootstrap_diff, summarize,
    walk_forward,
)

log = logging.getLogger(__name__)

# Gate for a FIRST production model: beat the naive hit-rate baseline on Brier score
# with a 95% CI that excludes zero for the points market, not be worse on any market,
# and have expected calibration error below this threshold.
MAX_ECE = 0.04


def production_model(s: Session) -> ModelVersion | None:
    return s.execute(select(ModelVersion).where(ModelVersion.status == "production")
                     .order_by(ModelVersion.promoted_at.desc())).scalars().first()


def _next_version(s: Session, name: str) -> str:
    n = s.execute(select(ModelVersion).where(ModelVersion.name == name)).scalars().all()
    return f"1.{len(n)}.0"


def evaluate_window(hist, calib_start: dt.date, eval_start: dt.date, eval_end: dt.date,
                    base: BaselineParams | None = None, calibrate: bool = True):
    """Walk-forward from `calib_start` (burn-in for the calibrator), score only [eval_start, eval_end].
    Returns (all predictions, metrics on the evaluation window)."""
    preds = walk_forward(hist, calib_start, eval_end, base)
    preds = calibrate_walk_forward(preds) if calibrate else preds.assign(model_p_raw=preds["model_p_over"])
    ev = preds[(preds["game_date"] >= eval_start) & (preds["game_date"] <= eval_end)]
    return preds, summarize(ev)


def train_and_register(s: Session, eval_start: dt.date | None = None, eval_game_days: int = 60,
                       promote: bool = False, calib_days: int = 365) -> ModelVersion:
    hist = load_history(s)
    if hist.empty:
        raise RuntimeError("no historical data; run `courtside backfill` first")
    last = hist["game_date"].max()
    dates = sorted(hist["game_date"].unique())
    if eval_start is None:
        eval_start = dates[-min(eval_game_days, len(dates))]  # last N dates that had games
    calib_start = max(dates[0] + dt.timedelta(days=30), eval_start - dt.timedelta(days=calib_days))
    log.info("walk-forward: calibration burn-in from %s, evaluation %s .. %s", calib_start, eval_start, last)
    preds, metrics = evaluate_window(hist, calib_start, eval_start, last)
    params = fit_params(hist, last + dt.timedelta(days=1))
    params.calibration = fit_final_calibration(preds)
    params.validated_markets = list(EVAL_MARKETS)
    mv = ModelVersion(name=params.name, version=params.version, status="candidate",
                      params=params.to_dict(), metrics=metrics, trained_through=last,
                      notes=f"walk-forward eval {eval_start}..{last}; calibrator burn-in from {calib_start}")
    if s.execute(select(ModelVersion).where(ModelVersion.name == mv.name, ModelVersion.version == mv.version)).first():
        mv.version = f"{params.version}+{_next_version(s, params.name).split('.')[1]}"
    s.add(mv)
    s.flush()
    audit(s, "learning", "model_registered", model_version_id=mv.id, version=mv.version)

    champ = production_model(s)
    ev_preds = preds[preds["game_date"] >= eval_start]
    decision = gate_first_model(metrics) if champ is None else gate_challenger(hist, calib_start, eval_start, last,
                                                                                 champ, ev_preds)
    mv.metrics = {**metrics, "gate": decision}
    if promote and decision["pass"]:
        promote_model(s, mv)
    return mv


def gate_first_model(metrics: dict) -> dict:
    reasons = []
    mk = metrics.get("markets", {})
    pts = mk.get("pts")
    if not pts:
        return {"pass": False, "reasons": ["no points-market evaluation"]}
    if not pts["brier_diff_ci95"][1] < 0:
        reasons.append("points Brier improvement over naive baseline not significant")
    for m, r in mk.items():
        if r["brier_diff_ci95"][0] > 0:
            reasons.append(f"{m}: significantly worse than naive baseline")
        if r["ece_model"] > MAX_ECE:
            reasons.append(f"{m}: calibration error {r['ece_model']:.3f} > {MAX_ECE}")
    return {"pass": not reasons, "reasons": reasons, "type": "first_model_vs_naive"}


def gate_challenger(hist, calib_start, eval_start, last, champ: ModelVersion, challenger_preds) -> dict:
    """Challenger must beat the champion on the same unseen window (paired bootstrap). The champion's
    calibrator is refit walk-forward too, so neither side benefits from in-window calibration."""
    cp = BaselineParams.from_dict(champ.params)
    # refit the champion's design walk-forward (base=cp), so its fitted parts never saw the window
    champ_preds = calibrate_walk_forward(walk_forward(hist, calib_start, last, base=cp))
    champ_preds = champ_preds[champ_preds["game_date"] >= eval_start]
    reasons, details = [], {}
    for m in EVAL_MARKETS:
        keys = ["game_date", "player_id", "market"]
        j = challenger_preds[challenger_preds.market == m].merge(
            champ_preds[champ_preds.market == m][keys + ["model_p_over"]], on=keys, suffixes=("", "_champ"))
        if len(j) < 200:
            continue
        y = j["over"].to_numpy()
        diff, lo, hi = paired_bootstrap_diff((j["model_p_over"].to_numpy() - y) ** 2,
                                             (j["model_p_over_champ"].to_numpy() - y) ** 2)
        details[m] = {"brier_diff": diff, "ci95": [lo, hi]}
        if lo > 0:
            reasons.append(f"{m}: significantly worse than champion")
    if not any(d["ci95"][1] < 0 for d in details.values()):
        reasons.append("no market shows a significant improvement over the champion")
    return {"pass": not reasons, "reasons": reasons, "type": "challenger_vs_champion",
            "champion_id": champ.id, "details": details,
            "note": "promotion also requires shadow testing on live slates (see docs)"}


def promote_model(s: Session, mv: ModelVersion) -> None:
    for old in s.execute(select(ModelVersion).where(ModelVersion.status == "production")).scalars():
        old.status = "retired"
    mv.status = "production"
    mv.promoted_at = utcnow()
    audit(s, "learning", "model_promoted", model_version_id=mv.id, version=mv.version)


def rollback(s: Session, to_id: int) -> ModelVersion:
    mv = s.get(ModelVersion, to_id)
    if mv is None:
        raise ValueError("unknown model version")
    promote_model(s, mv)
    audit(s, "learning", "model_rollback", model_version_id=to_id)
    return mv


# --------------------------------------------------------------------------- error attribution
def attribute_error(pred, actual_minutes: float | None, actual: float | None, stat_row, game) -> list[str]:
    """Heuristic post-mortem tags for a settled prediction. Descriptive only."""
    tags: list[str] = []
    if actual_minutes is None or actual is None:
        return ["did_not_play"]
    if pred.proj_minutes and abs(actual_minutes - pred.proj_minutes) / max(pred.proj_minutes, 1) > 0.25:
        tags.append("minutes_miss")
    if game.home_score is not None and game.away_score is not None and abs(game.home_score - game.away_score) >= 20:
        tags.append("blowout")
    if stat_row is not None and stat_row.pf >= 5:
        tags.append("foul_trouble")
    if not tags and not (pred.proj_p10 <= actual <= pred.proj_p90):
        tags.append("tail_outcome")
    if stat_row is not None and pred.market in ("pts", "fg3m", "pra", "pr", "pa") and stat_row.fga >= 8:
        fg = stat_row.fgm / stat_row.fga
        if fg < 0.33 or fg > 0.62:
            tags.append("shooting_variance")
    return tags or ["within_expected_range"]


def error_summary(preds) -> dict:
    tags: dict[str, int] = {}
    for p in preds:
        for t in p.error_tags or []:
            tags[t] = tags.get(t, 0) + 1
    errs = [p.actual - p.proj_mean for p in preds if p.actual is not None]
    return {"tag_counts": tags, "n": len(errs),
            "mean_error": float(np.mean(errs)) if errs else None,
            "mae": float(np.mean(np.abs(errs))) if errs else None}
