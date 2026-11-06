"""Performance analytics over SETTLED predictions. Record types are never mixed:
callers choose `published` (official picks), `paper` (all evaluated props) or
`real_money` (manually confirmed bets)."""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import ET
from ..models import ManualBet, ModelVersion, Prediction
from ..modeling.evaluate import brier, calibration_table, log_loss
from ..odds_math import implied_prob, profit_units


def _et_date(p: Prediction) -> dt.date:
    return p.created_at.replace(tzinfo=dt.timezone.utc).astimezone(ET).date()


def settled_predictions(s: Session, record_type: str) -> list[Prediction]:
    q = select(Prediction).where(Prediction.result.is_not(None)).order_by(Prediction.created_at)
    if record_type == "published":
        # the final published version of each pick at tip-off (superseded versions excluded)
        q = q.where(Prediction.published.is_(True), Prediction.status.in_(["locked", "active"]))
    elif record_type == "withdrawn":
        q = q.where(Prediction.published.is_(True), Prediction.status == "withdrawn")
    elif record_type == "paper":
        q = q.where(Prediction.status.in_(["locked", "active"]))
    return list(s.execute(q).scalars())


def _block(preds: list[Prediction]) -> dict:
    graded = [p for p in preds if p.result in ("win", "loss", "push")]
    w = sum(p.result == "win" for p in graded)
    l = sum(p.result == "loss" for p in graded)
    pu = sum(p.result == "push" for p in graded)
    pnl = [profit_units(p.result, p.price) for p in graded]
    staked = sum(1 for p in graded if p.result != "push")
    exp = [p.ev for p in graded]
    out = {"n": len(graded), "wins": w, "losses": l, "pushes": pu,
           "voids": sum(p.result == "void" for p in preds),
           "win_rate": w / (w + l) if (w + l) else None,
           "units": round(float(sum(pnl)), 3),
           "roi": float(sum(pnl) / staked) if staked else None,
           "expected_roi": float(np.mean(exp)) if exp else None,
           "max_drawdown": _max_drawdown(pnl)}
    wl = [p for p in graded if p.result != "push"]
    if wl:
        y = np.array([p.result == "win" for p in wl], float)
        pm = np.array([p.model_prob for p in wl])  # lines are almost always x.5, so push mass ~0
        out["brier"] = brier(pm, y)
        out["log_loss"] = log_loss(pm, y)
        mkt = [(_market_prob(p), yy) for p, yy in zip(wl, y) if _market_prob(p) is not None]
        if mkt:
            mp, my = np.array([m for m, _ in mkt]), np.array([v for _, v in mkt])
            out["brier_market"] = brier(mp, my)
        out["calibration"] = calibration_table(pm, y, bins=5)
    clv = [c for p in graded if (c := clv_of(p)) is not None]
    out["avg_clv"] = float(np.mean(clv)) if clv else None
    return out


def _market_prob(p: Prediction) -> float | None:
    return p.consensus_prob if p.consensus_prob is not None else p.novig_prob


def clv_of(p: Prediction) -> float | None:
    """Closing line value in implied-probability points (same line only)."""
    if p.closing_price is None or p.closing_line != p.line:
        return None
    return implied_prob(p.closing_price) - implied_prob(p.price)


def _max_drawdown(pnl: list[float]) -> float:
    if not pnl:
        return 0.0
    eq = np.cumsum(pnl)
    peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]
    return float(np.max(peak - eq))


def performance_report(s: Session, record_type: str = "published") -> dict:
    if record_type == "real_money":
        bets = list(s.execute(select(ManualBet).where(ManualBet.result.is_not(None))).scalars())
        pnl = [b.profit_units or 0.0 for b in bets]
        return {"record_type": "real_money", "n": len(bets), "units": float(sum(pnl)),
                "max_drawdown": _max_drawdown(pnl)}
    preds = settled_predictions(s, record_type)
    today = dt.datetime.now(ET).date()
    out: dict = {"record_type": record_type, "overall": _block(preds)}
    windows = {"today": 0, "last_7_days": 7, "last_30_days": 30}
    for name, days in windows.items():
        out[name] = _block([p for p in preds if (today - _et_date(p)).days <= days])
    groups = defaultdict(lambda: defaultdict(list))
    versions = {m.id: f"{m.name} {m.version}" for m in s.execute(select(ModelVersion)).scalars()}
    for p in preds:
        groups["by_market"][p.market].append(p)
        groups["by_book"][p.book].append(p)
        groups["by_model_version"][versions.get(p.model_version_id, "unknown")].append(p)
        groups["by_ev_band"][_ev_band(p.ev)].append(p)
        groups["by_prob_band"][_prob_band(p.model_prob)].append(p)
    for g, d in groups.items():
        out[g] = {k: _block(v) for k, v in sorted(d.items())}
    daily = defaultdict(list)
    for p in preds:
        daily[_et_date(p)].append(p)
    eq, series = 0.0, []
    for d in sorted(daily):
        b = _block(daily[d])
        eq += b["units"]
        series.append({"date": str(d), "units": b["units"], "cum_units": round(eq, 3), "n": b["n"]})
    out["daily_series"] = series
    return out


def _ev_band(ev: float) -> str:
    for lo, hi in ((-1, 0), (0, 0.03), (0.03, 0.06), (0.06, 0.10), (0.10, 10)):
        if lo <= ev < hi:
            return f"{lo:+.0%}..{hi:+.0%}" if hi < 10 else f">{lo:.0%}"
    return "other"


def _prob_band(p: float) -> str:
    lo = int(p * 10) / 10
    return f"{lo:.1f}-{lo + 0.1:.1f}"
