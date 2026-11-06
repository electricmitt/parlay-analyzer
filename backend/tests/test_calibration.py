import datetime as dt

import numpy as np
import pandas as pd
import pytest

from courtside.modeling import calibration as cal
from courtside.modeling.baseline import BASE_STATS, BaselineParams, playoff_factors


def _sigmoid(z):
    return 1 / (1 + np.exp(-z))


def test_calibrator_recovers_known_distortion():
    rng = np.random.default_rng(0)
    n = 20000
    true_logit = rng.normal(0, 1, n)
    y = (rng.uniform(size=n) < _sigmoid(true_logit)).astype(float)
    # an over-confident, over-biased forecaster: logit_raw = 1.5 * true + 0.3
    p_raw = _sigmoid(1.5 * true_logit + 0.3)
    model = cal.fit(p_raw, y, np.zeros(n), np.zeros(n))
    b0, b1 = model["coef"][:2]
    assert b1 == pytest.approx(1 / 1.5, abs=0.05) and b0 == pytest.approx(-0.3 / 1.5, abs=0.05)
    p_cal = cal.apply(model, p_raw)
    assert abs(p_cal.mean() - y.mean()) < 0.01


def test_identity_when_data_scarce_and_regime_terms_need_evidence():
    p = np.full(100, 0.6)
    m = cal.fit(p, np.ones(100), np.zeros(100), np.zeros(100))
    assert m["fitted"] is False
    assert cal.apply(m, 0.6)[0] == pytest.approx(0.6)
    rng = np.random.default_rng(1)
    p = rng.uniform(0.2, 0.8, 5000)
    y = (rng.uniform(size=5000) < p).astype(float)
    m = cal.fit(p, y, np.zeros(5000), np.zeros(5000))  # no playoff / early examples at all
    assert m["coef"][2] == pytest.approx(0, abs=1e-6) and m["coef"][3] == pytest.approx(0, abs=1e-6)
    assert cal.apply(None, 0.42)[0] == pytest.approx(0.42)


def test_playoff_factor_is_as_of_and_detects_drop():
    rows = []
    for pid in range(40):
        for i in range(30):  # regular season: 1.0 pts/min
            rows.append({"player_id": str(pid), "game_date": dt.date(2025, 1, 1) + dt.timedelta(days=2 * i),
                         "minutes": 30.0, "pts": 30, "season": 2025, "season_type": 2})
        for i in range(10):  # playoffs: 0.8 pts/min
            rows.append({"player_id": str(pid), "game_date": dt.date(2025, 4, 20) + dt.timedelta(days=2 * i),
                         "minutes": 30.0, "pts": 24, "season": 2025, "season_type": 3})
    h = pd.DataFrame(rows)
    for c in BASE_STATS:
        if c != "pts":
            h[c] = 0
    p = BaselineParams(playoff_shrink_games=400)
    before_playoffs = playoff_factors(h, dt.date(2025, 4, 20), p)
    assert before_playoffs["po_pts"] == 1.0 and before_playoffs["po_games"] == 0
    later = playoff_factors(h, dt.date(2025, 6, 1), p)
    n = 400  # 40 players x 10 playoff games
    assert later["po_pts"] == pytest.approx(1 + (0.8 - 1) * n / (n + 400))
