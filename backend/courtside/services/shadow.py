"""Shadow comparison: score the production model and a paper candidate on real closing-time
lines from finished games. Read-only: it writes nothing and publishes nothing.

Both models are scored on raw simulation probabilities (no calibration), and with only basic
history and minutes filters, so results are a comparison, not a replay of what was published.
"""
from __future__ import annotations

import copy
import datetime as dt

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Game, ModelVersion, OddsSnapshot
from ..modeling.baseline import BaselineParams, build_features, simulate
from ..modeling.data import load_history
from ..odds_math import no_vig_two_way

MARKET = "pts"
CANDIDATE_CHANGES = {"shrink_minutes": 0.0}  # no pull toward the position-wide scoring rate
MIN_GAMES, MIN_MINUTES, N_SIMS = 8, 10.0, 6000


def _logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def _logloss(p, y) -> float:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def _blend(model, market, w):
    return 1 / (1 + np.exp(-(_logit(market) + w * (_logit(model) - _logit(market)))))


def _decimal(american):
    a = np.asarray(american, dtype=float)
    return np.where(a > 0, 1 + a / 100, 1 - 100 / a)


def pretip_quotes(s: Session, start: dt.date, end: dt.date) -> pd.DataFrame:
    """Latest two-sided quote per (game, player, book) captured before tip-off, final games only."""
    rows = s.execute(
        select(OddsSnapshot, Game.game_date).join(Game, Game.id == OddsSnapshot.game_id)
        .where(Game.game_date >= start, Game.game_date <= end, Game.status == "STATUS_FINAL",
               OddsSnapshot.market == MARKET, OddsSnapshot.player_id.is_not(None),
               OddsSnapshot.over_price.is_not(None), OddsSnapshot.under_price.is_not(None),
               OddsSnapshot.fetched_at < Game.start_time)
        .order_by(OddsSnapshot.fetched_at.desc(), OddsSnapshot.id.desc())
    ).all()
    limit = dt.timedelta(minutes=get_settings().max_odds_age_min)
    newest: dict[str, dt.datetime] = {}
    seen, out = set(), []
    for sn, day in rows:
        newest.setdefault(sn.game_id, sn.fetched_at)  # rows arrive newest first
        key = (sn.game_id, sn.player_id, sn.book)
        if key not in seen and newest[sn.game_id] - sn.fetched_at <= limit:  # same pull, not leftovers
            seen.add(key)
            out.append({"game_id": sn.game_id, "game_date": day, "player_id": sn.player_id, "book": sn.book,
                        "line": sn.line, "over_price": sn.over_price, "under_price": sn.under_price,
                        "nv": no_vig_two_way(sn.over_price, sn.under_price)[0]})
    return pd.DataFrame(out)


def _score(q: pd.DataFrame, weights: tuple[float, ...], min_ev: float) -> dict:
    """q has one row per quote with columns cons, pm (model P(over)), y."""
    props = q.drop_duplicates(["game_id", "player_id", "line"])
    fit = minimize_scalar(lambda k: _logloss(_blend(props.pm, props.cons, k), props.y), bounds=(-1, 2), method="bounded")
    res = {"props": len(props), "market_logloss": _logloss(props.cons, props.y),
           "model_logloss": _logloss(props.pm, props.y), "best_model_weight": float(fit.x)}
    for w in weights:
        p = _blend(q.pm, q.cons, w)
        ev_o, ev_u = p * _decimal(q.over_price) - 1, (1 - p) * _decimal(q.under_price) - 1
        over = ev_o >= ev_u
        picks = q.assign(over=over, ev=np.maximum(ev_o, ev_u), price=np.where(over, q.over_price, q.under_price))
        picks = picks[picks.ev >= min_ev].sort_values("ev", ascending=False).drop_duplicates(["game_id", "player_id", "over"])
        won = picks.over == (picks.y == 1)
        res[f"w{w:g}"] = {"wins": int(won.sum()), "losses": int((~won).sum()),
                          "units": round(float((won * (_decimal(picks.price) - 1) - ~won).sum()), 2)}
    return res


def shadow_report(s: Session, start: dt.date, end: dt.date) -> dict:
    st = get_settings()
    quotes = pretip_quotes(s, start, end)
    if quotes.empty:
        return {"error": "no pre-tip odds for finished games in this range"}
    prod = BaselineParams.from_dict(s.execute(
        select(ModelVersion).where(ModelVersion.status == "production")).scalars().one().params)
    cand = copy.deepcopy(prod)
    for k, v in CANDIDATE_CHANGES.items():
        setattr(cand, k, v)
    hist = load_history(s, before=end + dt.timedelta(days=1))
    played = hist[(hist.game_date >= start) & (hist.minutes > 0)]
    q = quotes.merge(played[["game_id", "player_id", "pts"]], on=["game_id", "player_id"])
    q = q[q.pts != q.line].copy()  # pushes settle neither side
    if q.empty:
        return {"error": "no graded quotes in this range"}
    q["cons"] = q.groupby(["game_id", "player_id", "line"]).nv.transform("median")
    q["y"] = (q.pts > q.line).astype(int)
    targets = played[played.game_id.isin(q.game_id.unique())]
    weights = tuple(sorted({1.0, st.market_blend_weight}))
    out = {"start": str(start), "end": str(end), "nights": int(q.game_date.nunique()), "candidate_changes": CANDIDATE_CHANGES}
    for name, params in (("production", prod), ("candidate", cand)):
        feats = build_features(hist, targets, params)
        feats = feats[(feats.n_games >= MIN_GAMES) & (feats.mu_min >= MIN_MINUTES)]
        draws = {(r.game_id, r.player_id): simulate(r, params, n=N_SIMS, seed=st.random_seed + int(r.player_id) % 10_000,
                                                    markets=[MARKET])[MARKET] for _, r in feats.iterrows()}
        keys = list(zip(q.game_id, q.player_id))
        sub = q[[k in draws for k in keys]].copy()
        d = [draws[k] for k in zip(sub.game_id, sub.player_id)]
        sub["pm"] = [float((x > ln).sum() / max(1, (x != ln).sum())) for x, ln in zip(d, sub.line)]
        out[name] = _score(sub, weights, st.min_ev)
    return out
