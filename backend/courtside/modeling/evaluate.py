"""Walk-forward evaluation of the projection model.

There is no free archive of historical player-prop prices, so the backtest scores the
model's probability distribution on *proxy lines* (floor of the player's last-10 average
+ 0.5, which tracks how books typically set lines). Results are labelled "backtest /
proxy lines" everywhere they are shown and are never mixed with live records.

Baselines:
* naive_l10: P(over) = smoothed share of the last 10 games over the line
* mean baselines for MAE: last-10 average and season (last-82) average
"""
from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd

from . import calibration as cal
from .baseline import (
    BASE_STATS, BaselineParams, build_features, fit_dispersion, fit_position_prior, market_components,
)

EVAL_MARKETS = ["pts", "reb", "ast", "fg3m", "pra"]
MIN_HISTORY = 8
MIN_PROJ_MINUTES = 15.0


def fit_params(hist: pd.DataFrame, before: dt.date, base: BaselineParams | None = None,
               dispersion_window_days: int = 120) -> BaselineParams:
    p = BaselineParams.from_dict((base or BaselineParams()).to_dict())
    train = hist[hist["game_date"] < before]
    p.position_prior = fit_position_prior(train)
    recent = train[train["game_date"] >= before - dt.timedelta(days=dispersion_window_days)]
    if len(recent) < 2000:  # off-season gap: fall back to a longer window
        recent = train[train["game_date"] >= before - dt.timedelta(days=365)]
    feats = build_features(train, recent, p)
    p.dispersion = fit_dispersion(feats)
    return p


def mc_prob_over(feats: pd.DataFrame, p: BaselineParams, market: str, lines: np.ndarray,
                 n: int = 2000, seed: int = 11) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorised Monte Carlo: returns (p_over, p10, p90) per row."""
    rng = np.random.default_rng(seed)
    k = len(feats)
    mins = np.clip(rng.normal(feats["mu_min"].to_numpy()[:, None], feats["sd_min"].to_numpy()[:, None],
                              (k, n)), 0, 48)
    total = np.zeros((k, n))
    for s in market_components(market):
        mu = mins * (feats[f"rate_{s}"].to_numpy() * feats[f"opp_{s}"].fillna(1.0).to_numpy())[:, None]
        r = float(p.dispersion.get(s, 8.0))
        mu = np.maximum(mu, 1e-9)
        lam = mu if r >= 1e4 else rng.gamma(shape=r, scale=mu / r)
        total += rng.poisson(lam)
    p_over = (total > lines[:, None]).mean(axis=1)
    return p_over, np.percentile(total, 10, axis=1), np.percentile(total, 90, axis=1)


def _actual(df: pd.DataFrame, market: str) -> np.ndarray:
    return sum(df[c].to_numpy(float) for c in market_components(market))


def _feat(df: pd.DataFrame, prefix: str, market: str) -> np.ndarray:
    return sum(df[f"{prefix}_{c}"].to_numpy(float) for c in market_components(market))


def predict_block(hist: pd.DataFrame, block: pd.DataFrame, p: BaselineParams) -> pd.DataFrame:
    feats = build_features(hist, block, p)
    feats = feats[(feats["n_games"] >= MIN_HISTORY) & (feats["mu_min"] >= MIN_PROJ_MINUTES)
                  & (feats["minutes"] > 0)].copy()
    out = []
    for m in EVAL_MARKETS:
        if not len(feats):
            break
        l10 = _feat(feats, "l10", m)
        line = np.floor(l10) + 0.5
        mean = sum(feats["mu_min"].to_numpy() * feats[f"rate_{c}"].to_numpy()
                   * feats[f"opp_{c}"].fillna(1.0).to_numpy() for c in market_components(m))
        p_over, p10, p90 = mc_prob_over(feats, p, m, line)
        y = _actual(feats, m)
        out.append(pd.DataFrame({
            "game_date": feats["game_date"].to_numpy(), "player_id": feats["player_id"].to_numpy(),
            "market": m, "line": line, "actual": y, "model_mean": mean, "l10_mean": l10,
            "season_mean": _feat(feats, "season", m), "model_p_over": p_over,
            "naive_p_over": _naive_hit_rate(hist, feats, m, line),
            "p10": p10, "p90": p90, "over": (y > line).astype(float),
            "minutes_err": feats["minutes"].to_numpy() - feats["mu_min"].to_numpy(),
            "is_playoff": feats["is_playoff"].to_numpy(dtype=float),
            "early": (feats["n_current_season"] < p.new_season_games).to_numpy(dtype=float),
        }))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def _naive_hit_rate(hist: pd.DataFrame, feats: pd.DataFrame, market: str, line: np.ndarray) -> np.ndarray:
    played = hist[hist["minutes"] > 0]
    res = []
    for (pid, d), ln in zip(feats[["player_id", "game_date"]].itertuples(index=False), line):
        prior = played[(played["player_id"] == pid) & (played["game_date"] < d)].tail(10)
        hits = (_actual(prior, market) > ln).sum()
        res.append((hits + 1) / (len(prior) + 2))  # Laplace smoothing
    return np.array(res)


def walk_forward(hist: pd.DataFrame, eval_start: dt.date, eval_end: dt.date,
                 base: BaselineParams | None = None, step_days: int = 14,
                 fixed_params: BaselineParams | None = None) -> pd.DataFrame:
    """Refit on all data before each block, predict the block, move forward."""
    preds = []
    t = eval_start
    while t <= eval_end:
        t_end = min(t + dt.timedelta(days=step_days), eval_end + dt.timedelta(days=1))
        block = hist[(hist["game_date"] >= t) & (hist["game_date"] < t_end)]
        if len(block):
            p = fixed_params or fit_params(hist, t, base)
            preds.append(predict_block(hist[hist["game_date"] < t_end], block, p))
        t = t_end
    return pd.concat(preds, ignore_index=True) if preds else pd.DataFrame()


def calibrate_walk_forward(preds: pd.DataFrame, step_days: int = 14,
                           frozen: dict[str, dict] | None = None) -> pd.DataFrame:
    """Adds model_p_raw and replaces model_p_over with the calibrated probability.
    Each 14-day block is calibrated with a model fit only on earlier predictions.
    With `frozen` calibrators (e.g. a champion model's) nothing is refit."""
    preds = preds.copy()
    preds["model_p_raw"] = preds["model_p_over"]
    if not len(preds):
        return preds
    if frozen is not None:
        for m, g in preds.groupby("market"):
            preds.loc[g.index, "model_p_over"] = cal.apply(frozen.get(m), g["model_p_raw"], g["is_playoff"], g["early"])
        return preds
    start, end = preds["game_date"].min(), preds["game_date"].max()
    t = start
    while t <= end:
        t_end = t + dt.timedelta(days=step_days)
        for m in preds["market"].unique():
            hist_m = preds[(preds["market"] == m) & (preds["game_date"] < t)]
            blk = preds[(preds["market"] == m) & (preds["game_date"] >= t) & (preds["game_date"] < t_end)]
            if not len(blk):
                continue
            model = cal.fit(hist_m["model_p_raw"], hist_m["over"], hist_m["is_playoff"], hist_m["early"])
            preds.loc[blk.index, "model_p_over"] = cal.apply(model, blk["model_p_raw"], blk["is_playoff"], blk["early"])
        t = t_end
    return preds


def fit_final_calibration(preds: pd.DataFrame) -> dict[str, dict]:
    return {m: cal.fit(g["model_p_raw"], g["over"], g["is_playoff"], g["early"])
            for m, g in preds.groupby("market")}


# --------------------------------------------------------------------------- metrics
def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def log_loss(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def calibration_table(p: np.ndarray, y: np.ndarray, bins: int = 10) -> list[dict]:
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi) if hi < 1 else (p >= lo) & (p <= hi)
        if m.sum() == 0:
            continue
        out.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": int(m.sum()), "mean_pred": float(p[m].mean()),
                    "obs_rate": float(y[m].mean())})
    return out


def ece(p: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    tbl = calibration_table(p, y, bins)
    n = sum(r["n"] for r in tbl)
    return float(sum(r["n"] * abs(r["mean_pred"] - r["obs_rate"]) for r in tbl) / n) if n else math.nan


def paired_bootstrap_diff(a: np.ndarray, b: np.ndarray, n: int = 2000, seed: int = 3) -> tuple[float, float, float]:
    """Mean of (a - b) with a 95% bootstrap CI. Negative => a has lower loss."""
    rng = np.random.default_rng(seed)
    d = a - b
    idx = rng.integers(0, len(d), (n, len(d)))
    boots = d[idx].mean(axis=1)
    return float(d.mean()), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


def summarize(preds: pd.DataFrame) -> dict:
    out: dict = {"n_predictions": int(len(preds)), "label": "backtest / proxy lines (no historical prices)",
                 "markets": {}}
    if not len(preds):
        return out
    out["date_range"] = [str(preds["game_date"].min()), str(preds["game_date"].max())]
    for m, g in preds.groupby("market"):
        y = g["over"].to_numpy()
        mp, npo = g["model_p_over"].to_numpy(), g["naive_p_over"].to_numpy()
        diff, lo, hi = paired_bootstrap_diff((mp - y) ** 2, (npo - y) ** 2)
        out["markets"][m] = {
            "n": int(len(g)),
            "mae_model": float(np.mean(np.abs(g["model_mean"] - g["actual"]))),
            "mae_l10": float(np.mean(np.abs(g["l10_mean"] - g["actual"]))),
            "mae_season": float(np.mean(np.abs(g["season_mean"] - g["actual"]))),
            "rmse_model": float(np.sqrt(np.mean((g["model_mean"] - g["actual"]) ** 2))),
            "brier_model": brier(mp, y), "brier_naive": brier(npo, y),
            "brier_diff": diff, "brier_diff_ci95": [lo, hi],
            "logloss_model": log_loss(mp, y), "logloss_naive": log_loss(npo, y),
            "ece_model": ece(mp, y), "ece_naive": ece(npo, y),
            "coverage_80": float(np.mean((g["actual"] >= g["p10"]) & (g["actual"] <= g["p90"]))),
            **({"brier_raw": brier(g["model_p_raw"].to_numpy(), y), "ece_raw": ece(g["model_p_raw"].to_numpy(), y)}
               if "model_p_raw" in g else {}),
            "base_rate_over": float(y.mean()),
            "calibration": calibration_table(mp, y),
        }
    out["minutes_mae"] = float(preds.drop_duplicates(["game_date", "player_id"])["minutes_err"].abs().mean())
    return out
