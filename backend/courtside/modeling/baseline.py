"""Agent 2 — Player Performance Prediction (Phase 1 baseline).

Interpretable model, one code path for backtest and live use:

    stat ~ NegBin(mean = minutes x rate_per_min x opponent_factor, dispersion r_stat)
    minutes ~ Normal(mu_min, sd_min) truncated to [0, 48]

* mu_min / sd_min: exponentially weighted mean / std of recent minutes (games played).
* rate_per_min: minutes-weighted EWMA of the player's per-minute production, shrunk
  toward a position prior when the sample is small.
* opponent_factor: opponent's recent stat-allowed per game relative to league, shrunk
  toward 1 and clipped (captures defensive strength and pace).
* r_stat: fitted by method of moments on prior (out-of-sample) residuals.

Strict as-of semantics: every feature for a game on date D uses only rows with
game_date < D. `build_features` is the single entry point for both training and
serving, so there is no train/serve skew.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

BASE_STATS = ["pts", "reb", "ast", "fg3m", "stl", "blk", "tov"]
COMBOS = {"pra": ["pts", "reb", "ast"], "pr": ["pts", "reb"], "pa": ["pts", "ast"], "ra": ["reb", "ast"]}
MARKETS = BASE_STATS + list(COMBOS)
MARKET_LABELS = {
    "pts": "Points", "reb": "Rebounds", "ast": "Assists", "fg3m": "3-Pointers Made",
    "stl": "Steals", "blk": "Blocks", "tov": "Turnovers", "pra": "Pts+Reb+Ast",
    "pr": "Pts+Reb", "pa": "Pts+Ast", "ra": "Reb+Ast",
}


def market_components(market: str) -> list[str]:
    return COMBOS.get(market, [market])


@dataclass
class BaselineParams:
    name: str = "baseline_ewma_nb"
    version: str = "1.3.0"
    hl_minutes: float = 4.0         # games
    hl_minutes_sd: float = 8.0
    hl_rate: float = 12.0
    min_sd_floor: float = 2.5
    shrink_minutes: float = 150.0   # prior weight in minutes for rate shrinkage
    opp_window: int = 20            # team games
    opp_shrink_games: float = 15.0
    opp_clip: float = 0.12
    league_window_days: int = 60
    lookback_days: int = 400
    offseason_gap_days: int = 60      # a gap this long marks a season boundary
    offseason_weight: float = 0.25    # weight multiplier for games before the boundary
    new_season_games: int = 10        # widen minutes uncertainty until this many current-season games
    new_season_sd_frac: float = 0.2   # minimum minutes sd as a fraction of mu while widened
    use_playoff_factor: bool = True
    playoff_shrink_games: float = 400.0  # prior weight (player-games) toward "no playoff effect"
    playoff_clip: float = 0.15
    dispersion: dict[str, float] = field(default_factory=lambda: {s: 8.0 for s in BASE_STATS})
    calibration: dict[str, dict] = field(default_factory=dict)  # market -> calibration.fit() output
    validated_markets: list[str] = field(default_factory=list)  # markets the backtest covered
    position_prior: dict[str, dict[str, float]] = field(default_factory=dict)  # pos -> stat -> per-min

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> "BaselineParams":
        p = cls()
        for k, v in (d or {}).items():
            if hasattr(p, k):
                setattr(p, k, v)
        return p


STAT_COLS = ["game_id", "player_id", "team_id", "opponent_id", "game_date", "is_home", "starter",
             "minutes"] + BASE_STATS + ["pf", "position", "season", "season_type"]


def _played(hist: pd.DataFrame) -> pd.DataFrame:
    return hist[(hist["minutes"] > 0)].copy()


def fit_position_prior(hist: pd.DataFrame) -> dict[str, dict[str, float]]:
    h = _played(hist)
    h["position"] = h["position"].fillna("NA")
    out: dict[str, dict[str, float]] = {}
    tot_min = h["minutes"].sum()
    out["ALL"] = {s: float(h[s].sum() / tot_min) for s in BASE_STATS} if tot_min else {s: 0.0 for s in BASE_STATS}
    for pos, g in h.groupby("position"):
        m = g["minutes"].sum()
        if m > 2000:
            out[str(pos)] = {s: float(g[s].sum() / m) for s in BASE_STATS}
    return out


def _opponent_factors(hist: pd.DataFrame, targets: pd.DataFrame, p: BaselineParams) -> pd.DataFrame:
    """For each target (opponent_id, game_date): stat-allowed factor per base stat, as-of."""
    h = _played(hist)
    allowed = h.groupby(["game_id", "opponent_id", "game_date"], as_index=False)[BASE_STATS].sum()
    allowed = allowed.sort_values("game_date")
    keys = targets[["opponent_id", "game_date"]].drop_duplicates()
    rows = []
    for (opp, d) in keys.itertuples(index=False):
        prior = allowed[allowed["game_date"] < d]
        league = prior[prior["game_date"] >= d - dt.timedelta(days=p.league_window_days)]
        team = prior[prior["opponent_id"] == opp].tail(p.opp_window)
        rec = {"opponent_id": opp, "game_date": d, "opp_games": len(team)}
        for s in BASE_STATS:
            lg = league[s].mean() if len(league) else np.nan
            if len(team) == 0 or not lg or np.isnan(lg):
                rec[f"opp_{s}"] = 1.0
                continue
            raw = team[s].mean() / lg
            w = len(team) / (len(team) + p.opp_shrink_games)
            rec[f"opp_{s}"] = float(np.clip(1 + (raw - 1) * w, 1 - p.opp_clip, 1 + p.opp_clip))
        rows.append(rec)
    return pd.DataFrame(rows)


def playoff_factors(hist: pd.DataFrame, d: dt.date, p: BaselineParams) -> dict[str, float]:
    """As-of league-wide playoff/regular-season per-minute production ratio for the same players
    in the same season, shrunk toward 1. Uses only games before `d`."""
    h = _played(hist)
    h = h[(h["game_date"] < d) & (h["game_date"] >= d - dt.timedelta(days=p.lookback_days))]
    out = {f"po_{s}": 1.0 for s in BASE_STATS}
    out["po_games"] = 0
    if "season_type" not in h or not (h["season_type"] == 3).any():
        return out
    agg = h.groupby(["player_id", "season", "season_type"])[["minutes"] + BASE_STATS].sum().reset_index()
    rs = agg[agg["season_type"] == 2].set_index(["player_id", "season"])
    po = agg[agg["season_type"] == 3].set_index(["player_id", "season"])
    both = po.add_suffix("_po").join(rs.add_suffix("_rs"), how="inner")
    both = both[both["minutes_rs"] >= 200]
    n = int(h[(h["season_type"] == 3)].shape[0])
    out["po_games"] = n
    w = n / (n + p.playoff_shrink_games)
    for s in BASE_STATS:
        expected = (both["minutes_po"] * both[f"{s}_rs"] / both["minutes_rs"]).sum()
        if expected > 0:
            raw = both[f"{s}_po"].sum() / expected
            out[f"po_{s}"] = float(np.clip(1 + (raw - 1) * w, 1 - p.playoff_clip, 1 + p.playoff_clip))
    return out


def build_features(hist: pd.DataFrame, targets: pd.DataFrame, p: BaselineParams) -> pd.DataFrame:
    """hist: player-game rows (STAT_COLS). targets: rows with player_id, game_date, opponent_id
    (and optionally team_id/game_id). Returns targets + features; rows with no history get NaN."""
    hist = hist.sort_values(["player_id", "game_date"])
    played = _played(hist)
    out = []
    targets = targets.copy()
    for pid, tg in targets.groupby("player_id"):
        ph = played[played["player_id"] == pid]
        for idx, t in tg.iterrows():
            d = t["game_date"]
            prior = ph[(ph["game_date"] < d) & (ph["game_date"] >= d - dt.timedelta(days=p.lookback_days))]
            out.append(_player_features(idx, prior, d, p))
    feats = pd.DataFrame(out).set_index("idx") if out else pd.DataFrame()
    res = targets.join(feats)
    opp = _opponent_factors(hist, targets, p)
    if len(opp):
        res = res.merge(opp, on=["opponent_id", "game_date"], how="left")
    # Playoff adjustment, folded into the opponent factor so every consumer applies it.
    is_po = (res["season_type"] == 3) if "season_type" in res else pd.Series(False, index=res.index)
    res["is_playoff"] = is_po.astype(bool).to_numpy()
    for s in BASE_STATS:
        res[f"po_{s}"] = 1.0
    if p.use_playoff_factor and is_po.any():
        for d in res.loc[is_po, "game_date"].unique():
            f = playoff_factors(hist, d, p)
            m = is_po & (res["game_date"] == d)
            for s in BASE_STATS:
                res.loc[m, f"po_{s}"] = f[f"po_{s}"]
    for s in BASE_STATS:
        if f"opp_{s}" in res:
            res[f"opp_{s}"] = res[f"opp_{s}"].fillna(1.0) * res[f"po_{s}"]
    return res


def _ew_weights(n: int, halflife: float) -> np.ndarray:
    # most recent game gets weight 1
    ages = np.arange(n)[::-1]
    return 0.5 ** (ages / halflife)


def _player_features(idx, prior: pd.DataFrame, d: dt.date, p: BaselineParams) -> dict:
    rec: dict = {"idx": idx, "n_games": len(prior)}
    if len(prior) == 0:
        return rec
    mins = prior["minutes"].to_numpy(float)
    # Season boundary: games before the most recent long gap (incl. the gap up to D) are down-weighted,
    # because roles and rotations reset over an off-season.
    dates = list(prior["game_date"]) + [d]
    boundary = 0
    for i in range(1, len(dates)):
        if (dates[i] - dates[i - 1]).days >= p.offseason_gap_days:
            boundary = i
    season_mult = np.where(np.arange(len(mins)) < boundary, p.offseason_weight, 1.0)
    n_current = int(len(mins) - boundary)
    rec["n_current_season"] = n_current
    wm = _ew_weights(len(mins), p.hl_minutes) * season_mult
    mu_min = float(np.sum(wm * mins) / wm.sum())
    ws = _ew_weights(len(mins), p.hl_minutes_sd) * season_mult
    var = float(np.sum(ws * (mins - np.sum(ws * mins) / ws.sum()) ** 2) / ws.sum())
    sd = max(np.sqrt(var), p.min_sd_floor)
    if n_current < p.new_season_games:
        sd = max(sd, p.new_season_sd_frac * mu_min)
    rec["mu_min"] = mu_min
    rec["sd_min"] = sd
    last = prior.iloc[-1]
    rec["days_since_last"] = (d - last["game_date"]).days
    rec["last_team_id"] = last["team_id"]
    rec["last5_min"] = float(prior["minutes"].tail(5).mean())
    rec["season_min"] = float(prior[prior["game_date"] >= d - dt.timedelta(days=200)]["minutes"].mean()) \
        if (prior["game_date"] >= d - dt.timedelta(days=200)).any() else mu_min
    pos = prior["position"].iloc[-1] if "position" in prior and pd.notna(prior["position"].iloc[-1]) else "NA"
    pri = p.position_prior.get(str(pos)) or p.position_prior.get("ALL") or {}
    wr = _ew_weights(len(mins), p.hl_rate)  # skill (per-minute rate) carries across seasons; no boundary discount
    eff_min = float(np.sum(wr * mins))
    w_shrink = eff_min / (eff_min + p.shrink_minutes)
    for s in BASE_STATS:
        vals = prior[s].to_numpy(float)
        raw = float(np.sum(wr * vals) / max(eff_min, 1e-9))
        prior_rate = pri.get(s, raw)
        rec[f"rate_{s}"] = w_shrink * raw + (1 - w_shrink) * prior_rate
        rec[f"l10_{s}"] = float(vals[-10:].mean())
        rec[f"l5_{s}"] = float(vals[-5:].mean())
        rec[f"season_{s}"] = float(vals[-82:].mean())
    rec["feat_position"] = pos
    return rec


def expected_mean(row: pd.Series | dict, stat: str, minutes: float | None = None) -> float:
    m = row["mu_min"] if minutes is None else minutes
    return float(m * row[f"rate_{stat}"] * row.get(f"opp_{stat}", 1.0))


# --------------------------------------------------------------------------- simulation
def simulate(row: dict | pd.Series, p: BaselineParams, n: int = 20000, seed: int = 7,
             markets: list[str] | None = None) -> dict[str, np.ndarray]:
    """Monte Carlo draws for each requested market. Combos share the minutes draw, which
    induces the positive correlation that comes from playing time."""
    rng = np.random.default_rng(seed)
    markets = markets or MARKETS
    needed = sorted({c for m in markets for c in market_components(m)})
    minutes = np.clip(rng.normal(row["mu_min"], row["sd_min"], n), 0, 48)
    draws: dict[str, np.ndarray] = {}
    for s in needed:
        mu = minutes * row[f"rate_{s}"] * float(row.get(f"opp_{s}", 1.0) or 1.0)
        r = float(p.dispersion.get(s, 8.0))
        draws[s] = _negbin(rng, mu, r)
    out = {m: sum(draws[c] for c in market_components(m)) for m in markets}
    out["_minutes"] = minutes
    return out


def _negbin(rng: np.random.Generator, mu: np.ndarray, r: float) -> np.ndarray:
    mu = np.maximum(mu, 1e-9)
    if r >= 1e4:
        return rng.poisson(mu)
    lam = rng.gamma(shape=r, scale=mu / r)  # Gamma-Poisson mixture
    return rng.poisson(lam)


def prob_over_under(draws: np.ndarray, line: float) -> tuple[float, float, float]:
    over = float(np.mean(draws > line))
    push = float(np.mean(draws == line))
    return over, 1.0 - over - push, push


def summarize(draws: np.ndarray) -> dict[str, float]:
    return {"mean": float(draws.mean()), "p10": float(np.percentile(draws, 10)),
            "p50": float(np.percentile(draws, 50)), "p90": float(np.percentile(draws, 90))}


# --------------------------------------------------------------------------- fitting
def fit_dispersion(df: pd.DataFrame) -> dict[str, float]:
    """Method of moments for NB r using the conditional mean given ACTUAL minutes,
    so minutes uncertainty (modelled separately) is not double counted.
    `df` = build_features output whose target rows carry the actual stats."""
    out = {}
    df = df[(df["n_games"] >= 5) & (df["minutes"] > 0)]
    for s in BASE_STATS:
        mu = df["minutes"] * df[f"rate_{s}"] * df[f"opp_{s}"].fillna(1.0)
        y = df[s]
        excess = float(((y - mu) ** 2 - mu).sum())
        if len(df) < 200 or excess <= 0:
            out[s] = 1e4  # no overdispersion detected -> Poisson
        else:
            out[s] = float(np.clip((mu ** 2).sum() / excess, 0.5, 1e4))
    return out
