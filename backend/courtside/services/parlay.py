"""Parlay analysis (EXPERIMENTAL, not walk-forward validated). A read-only estimate: nothing
here is published, stored or recommended, and it never changes a prediction.

Joint probability uses a Gaussian copula over each leg's model probability, so legs are never
simply multiplied when they share a game. Correlation for a same-game pair is estimated from the
two players' history: each stat minus that player's trailing 10-game mean, over the games both
played, shrunk toward zero. Pairs with too few shared games use zero and are flagged.

Prices: a parlay is one bet at one book. Multiplying decimal odds is only a fair estimate of the
payout when every leg is at the same book and in a different game. Same-game parlays are repriced
by the book, so EV is withheld until the user enters the quoted price.
"""
from __future__ import annotations

import datetime as dt
from itertools import combinations

import numpy as np
import pandas as pd
from scipy.stats import norm
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Game, Player, PlayerGameStat, Prediction, utcnow
from ..modeling.baseline import MARKET_LABELS, market_components
from ..odds_math import american_to_decimal, decimal_to_american

MIN_SHARED_GAMES = 20
SHRINK_K = 30.0
N_DRAWS = 200_000
LEG_SENSITIVITY = 0.03    # +/- applied to each leg's probability in the sensitivity range
FALLBACK_RHO_SE = 0.20    # correlation uncertainty assumed for pairs with too little history
MAX_LEGS = 6
STAT_FIELDS = ["pts", "reb", "ast", "fg3m", "stl", "blk", "tov"]


def _residual_frame(s: Session, player_ids: list[str]) -> pd.DataFrame:
    rows = s.execute(select(PlayerGameStat).where(PlayerGameStat.player_id.in_(player_ids),
                                                  PlayerGameStat.dnp.is_(False),
                                                  PlayerGameStat.minutes > 0)
                     .order_by(PlayerGameStat.game_date)).scalars().all()
    df = pd.DataFrame([{"player_id": r.player_id, "game_id": r.game_id, **{k: getattr(r, k) for k in STAT_FIELDS}}
                       for r in rows])
    return df


def _market_residuals(df: pd.DataFrame, player_id: str, market: str) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=float)
    sub = df[df["player_id"] == player_id]
    comps = [c for c in market_components(market) if c in STAT_FIELDS]
    if sub.empty or not comps:
        return pd.Series(dtype=float)
    values = sub[comps].sum(axis=1)
    trailing = values.shift(1).rolling(10, min_periods=5).mean()
    return (values - trailing).set_axis(sub["game_id"]).dropna()


def pair_correlation(a: pd.Series, b: pd.Series) -> tuple[float, int]:
    """Shrunk correlation of two residual series over shared games, and the shared-game count."""
    shared = a.index.intersection(b.index)
    n = len(shared)
    if n < MIN_SHARED_GAMES:
        return 0.0, n
    x, y = a.loc[shared].to_numpy(float), b.loc[shared].to_numpy(float)
    if x.std() == 0 or y.std() == 0:
        return 0.0, n
    return float(np.corrcoef(x, y)[0, 1] * n / (n + SHRINK_K)), n


def _nearest_correlation(c: np.ndarray) -> np.ndarray:
    vals, vecs = np.linalg.eigh(c)
    fixed = vecs @ np.diag(np.clip(vals, 1e-6, None)) @ vecs.T
    d = np.sqrt(np.diag(fixed))
    return fixed / np.outer(d, d)


def joint_probability(probs: list[float], corr: np.ndarray, seed: int) -> float:
    """P(every leg wins) with Gaussian-copula dependence between the legs' win indicators."""
    z = np.random.default_rng(seed).standard_normal((N_DRAWS, len(probs)))
    chol = np.linalg.cholesky(_nearest_correlation(corr))
    thresholds = norm.ppf(np.clip(probs, 1e-4, 1 - 1e-4))
    return float(np.mean(np.all(z @ chol.T < thresholds, axis=1)))


def _basis(a: Prediction, b: Prediction, pa: Player, pb: Player) -> str:
    if a.player_id == b.player_id:
        return "same player"
    return "teammates" if pa.team_id and pa.team_id == pb.team_id else "opponents"


def analyze_parlay(s: Session, prediction_ids: list[int], quoted_price: int | None = None) -> dict:
    if len(set(prediction_ids)) != len(prediction_ids):
        raise ValueError("the same leg was selected twice")
    if not 2 <= len(prediction_ids) <= MAX_LEGS:
        raise ValueError(f"a parlay needs 2 to {MAX_LEGS} legs")
    if quoted_price is not None and -100 < quoted_price < 100:
        raise ValueError("American odds must be <= -100 or >= +100")
    preds = [s.get(Prediction, i) for i in prediction_ids]
    if any(p is None for p in preds):
        raise ValueError("unknown prediction")
    now = utcnow()
    games = {p.game_id: s.get(Game, p.game_id) for p in preds}
    players = {p.player_id: s.get(Player, p.player_id) for p in preds}
    for p in preds:
        name = players[p.player_id].name
        if p.status != "active":
            raise ValueError(f"{name} is no longer an active prop ({p.status})")
        if games[p.game_id].start_time <= now:
            raise ValueError(f"{name}'s game has already started")
    for a, b in combinations(preds, 2):
        if a.player_id == b.player_id and a.market == b.market:
            raise ValueError(f"{players[a.player_id].name} has two legs in the same market")

    warnings: list[dict] = []
    frame = _residual_frame(s, sorted({p.player_id for p in preds if any(
        q is not p and q.game_id == p.game_id for q in preds)}))
    k = len(preds)
    corr, se = np.eye(k), np.zeros((k, k))
    pairs = []
    for i, j in combinations(range(k), 2):
        a, b = preds[i], preds[j]
        if a.game_id != b.game_id:
            continue  # treated as independent; a real simplification, surfaced in `method`
        pa, pb = players[a.player_id], players[b.player_id]
        raw, n = pair_correlation(_market_residuals(frame, a.player_id, a.market),
                                  _market_residuals(frame, b.player_id, b.market))
        sufficient = n >= MIN_SHARED_GAMES
        sign = (1 if a.side == "over" else -1) * (1 if b.side == "over" else -1)
        rho = float(np.clip(raw * sign, -0.9, 0.9))
        corr[i, j] = corr[j, i] = rho
        se[i, j] = se[j, i] = 1 / np.sqrt(n - 3) if sufficient else FALLBACK_RHO_SE
        pairs.append({"a": pa.name, "b": pb.name, "a_market": MARKET_LABELS.get(a.market, a.market),
                      "b_market": MARKET_LABELS.get(b.market, b.market), "basis": _basis(a, b, pa, pb),
                      "rho": round(rho, 3), "shared_games": n, "sufficient_history": sufficient})
        if not sufficient:
            warnings.append({"level": "serious", "code": "insufficient_history",
                             "message": f"{pa.name} and {pb.name} share only {n} games. Their correlation is "
                                        "unknown and was set to zero, so the joint estimate is weak."})
        elif abs(rho) >= 0.15:
            direction = "win together more often" if rho > 0 else "work against each other"
            warnings.append({"level": "warning", "code": "correlated",
                             "message": f"{pa.name} and {pb.name} are correlated ({rho:+.2f}, {n} games): "
                                        f"these legs tend to {direction}."})

    probs = [p.model_prob for p in preds]
    seed = get_settings().random_seed
    independent = float(np.prod(probs))
    joint = joint_probability(probs, corr, seed)
    low = joint_probability([max(x - LEG_SENSITIVITY, 0.01) for x in probs],
                            np.clip(corr - se, -0.9, 0.9) * (1 - np.eye(k)) + np.eye(k), seed)
    high = joint_probability([min(x + LEG_SENSITIVITY, 0.99) for x in probs],
                             np.clip(corr + se, -0.9, 0.9) * (1 - np.eye(k)) + np.eye(k), seed)

    multiplied = float(np.prod([american_to_decimal(p.price) for p in preds]))
    same_game = len(games) < k
    mixed_books = len({p.book for p in preds}) > 1
    if quoted_price is not None:
        decimal, source = american_to_decimal(quoted_price), "quoted"
    elif same_game or mixed_books:
        decimal, source = None, None
    else:
        decimal, source = multiplied, "multiplied"
    if mixed_books:
        warnings.append({"level": "serious", "code": "mixed_books",
                         "message": "These legs are priced at different books, but a parlay is one bet at one book. "
                                    "Enter the price your book quotes to see EV."})
    if same_game and quoted_price is None:
        warnings.append({"level": "warning", "code": "sgp_price_needed",
                         "message": "Books reprice same-game parlays for correlation, so multiplied odds would "
                                    "overstate the payout. Enter your book's quoted price to see EV."})
    for p in preds:
        name = players[p.player_id].name
        age = (now - p.odds_fetched_at).total_seconds() / 60
        if age > get_settings().max_odds_age_min:
            warnings.append({"level": "warning", "code": "stale_odds",
                             "message": f"{name}'s price is {age:.0f} min old and may have moved."})
        if not p.eligible:
            warnings.append({"level": "warning", "code": "not_eligible",
                             "message": f"{name} did not pass every single-prop filter: {'; '.join(p.reasons)}"})

    # Descriptive only, and never "low": even the likeliest parlays here lose more often than a single leg.
    risk = "elevated" if joint >= 0.40 else "high" if joint >= 0.20 else "very high"
    return {
        "status": "experimental",
        "method": "Gaussian copula on model leg probabilities. Same-game correlations are estimated from shrunk "
                  "historical residuals; legs in different games are treated as independent. Not walk-forward validated.",
        "legs": [{"id": p.id, "player": players[p.player_id].name, "market_label": MARKET_LABELS.get(p.market, p.market),
                  "side": p.side, "line": p.line, "book": p.book, "price": p.price, "model_prob": p.model_prob,
                  "game_id": p.game_id, "eligible": p.eligible, "published": p.published} for p in preds],
        "pairs": pairs,
        "independent_prob": independent,
        "joint_prob": joint,
        "joint_low": low,
        "joint_high": high,
        "sensitivity_note": f"Range moves each leg by +/-{LEG_SENSITIVITY:.0%} and each correlation by about one "
                            "standard error. It is a sensitivity check, not a confidence interval.",
        "multiplied_decimal": multiplied,
        "price": None if decimal is None else {"decimal": decimal, "american": decimal_to_american(decimal), "source": source},
        "ev": None if decimal is None else joint * decimal - 1,
        "ev_low": None if decimal is None else low * decimal - 1,
        "ev_high": None if decimal is None else high * decimal - 1,
        "risk_level": risk,
        "warnings": warnings,
        "computed_at": now.replace(tzinfo=dt.timezone.utc).isoformat(),
    }
