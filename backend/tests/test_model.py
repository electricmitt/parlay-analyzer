import datetime as dt

import numpy as np
import pandas as pd
import pytest

from courtside.modeling.baseline import BaselineParams, build_features, prob_over_under, simulate
from courtside.modeling.data import load_history
from courtside.modeling.evaluate import calibration_table, paired_bootstrap_diff

from .conftest import make_league


def test_features_are_as_of_no_leakage(session):
    today = dt.date(2026, 3, 1)
    make_league(session, days=30, today=today)
    hist = load_history(session)
    p = BaselineParams(position_prior={"ALL": {s: 0.5 for s in ["pts", "reb", "ast", "fg3m", "stl", "blk", "tov"]}})
    target_day = hist["game_date"].iloc[len(hist) // 2]
    tgt = pd.DataFrame([{"player_id": "100", "game_date": target_day, "opponent_id": "2", "team_id": "1"}])
    f1 = build_features(hist, tgt, p).iloc[0]
    # Corrupt every row on/after the target date: features must not change.
    poisoned = hist.copy()
    mask = poisoned["game_date"] >= target_day
    poisoned.loc[mask, ["pts", "minutes", "reb"]] = 999
    f2 = build_features(poisoned, tgt, p).iloc[0]
    for k in ("mu_min", "rate_pts", "rate_reb", "n_games", "opp_pts"):
        assert f1[k] == pytest.approx(f2[k]), k


def test_simulation_matches_expected_mean():
    row = {"mu_min": 30.0, "sd_min": 3.0, **{f"rate_{s}": r for s, r in
           {"pts": 0.8, "reb": 0.25, "ast": 0.2, "fg3m": 0.08, "stl": 0.03, "blk": 0.02, "tov": 0.07}.items()},
           "opp_pts": 1.05}
    p = BaselineParams(dispersion={"pts": 10.0, "reb": 20.0, "ast": 15.0, "fg3m": 1e4, "stl": 1e4, "blk": 1e4,
                                   "tov": 1e4})
    d = simulate(row, p, n=40000, seed=1)
    assert d["pts"].mean() == pytest.approx(30 * 0.8 * 1.05, rel=0.02)
    assert d["pra"].mean() == pytest.approx(d["pts"].mean() + d["reb"].mean() + d["ast"].mean())
    # combos built from shared minutes are positively correlated
    assert np.corrcoef(d["pts"], d["reb"])[0, 1] > 0
    o, u, push = prob_over_under(d["pts"], 25.5)
    assert o + u + push == pytest.approx(1.0) and push == 0.0
    o, u, push = prob_over_under(d["pts"], 25.0)
    assert push > 0


def test_simulation_reproducible():
    row = {"mu_min": 25.0, "sd_min": 4.0, **{f"rate_{s}": 0.1 for s in
                                             ["pts", "reb", "ast", "fg3m", "stl", "blk", "tov"]}}
    p = BaselineParams()
    assert np.array_equal(simulate(row, p, n=1000, seed=5)["pts"], simulate(row, p, n=1000, seed=5)["pts"])


def test_calibration_and_bootstrap():
    rng = np.random.default_rng(0)
    p = rng.uniform(0, 1, 5000)
    y = (rng.uniform(0, 1, 5000) < p).astype(float)
    tbl = calibration_table(p, y)
    assert all(abs(r["mean_pred"] - r["obs_rate"]) < 0.06 for r in tbl)
    good, bad = (p - y) ** 2, (0.5 - y) ** 2
    diff, lo, hi = paired_bootstrap_diff(good, bad)
    assert hi < 0  # calibrated forecasts beat a coin flip, significantly


def test_season_boundary_discounts_minutes_not_skill():
    """Regression: an off-season gap should down-weight old minutes but not per-minute skill."""
    import datetime as dt
    rows = []
    d0 = dt.date(2026, 1, 1)
    for i in range(30):  # last season: 36 min, 1.0 pts/min
        rows.append({"player_id": "p", "game_date": d0 + dt.timedelta(days=2 * i), "minutes": 36.0, "pts": 36})
    d1 = dt.date(2026, 10, 21)
    for i in range(3):  # new season: 24 min, 1.0 pts/min
        rows.append({"player_id": "p", "game_date": d1 + dt.timedelta(days=2 * i), "minutes": 24.0, "pts": 24})
    hist = pd.DataFrame(rows)
    for c in ["reb", "ast", "fg3m", "stl", "blk", "tov"]:
        hist[c] = 0
    hist["position"], hist["team_id"], hist["opponent_id"], hist["game_id"] = "G", "1", "2", range(len(hist))
    prior = {"ALL": {s: 0.4 for s in ["pts", "reb", "ast", "fg3m", "stl", "blk", "tov"]}}
    p = BaselineParams(position_prior=prior)
    tgt = pd.DataFrame([{"player_id": "p", "game_date": d1 + dt.timedelta(days=7), "opponent_id": "2", "team_id": "1"}])
    f = build_features(hist, tgt, p).iloc[0]
    assert f["n_current_season"] == 3
    no_boundary = build_features(hist, tgt, BaselineParams(position_prior=prior, offseason_weight=1.0)).iloc[0]
    assert f["mu_min"] < no_boundary["mu_min"] - 2  # old-season minutes are discounted
    assert f["rate_pts"] == pytest.approx(no_boundary["rate_pts"])  # ...but skill is not
    assert f["rate_pts"] > 0.8  # mostly the player's own 1.0 rate, not the 0.4 position prior
    assert f["sd_min"] >= 0.2 * f["mu_min"]  # widened uncertainty early in the season
