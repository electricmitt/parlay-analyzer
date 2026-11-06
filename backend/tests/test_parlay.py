"""Parlay analysis: correlation handling and when a price (and so EV) may be shown."""
import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select

from courtside.models import AnalysisRun, Prediction, utcnow
from courtside.services.analysis import analyze_day
from courtside.services.ingest import et_date
from courtside.services.parlay import MIN_SHARED_GAMES, analyze_parlay, joint_probability, pair_correlation

from .conftest import add_injury_snapshot, add_odds, add_production_model, add_today_game, make_league


def test_joint_matches_product_when_independent():
    assert joint_probability([0.6, 0.5], np.eye(2), seed=1) == pytest.approx(0.30, abs=0.005)


def test_positive_correlation_raises_joint_and_negative_lowers_it():
    corr = lambda r: np.array([[1, r], [r, 1]])
    assert joint_probability([0.6, 0.5], corr(0.5), 1) > 0.33
    assert joint_probability([0.6, 0.5], corr(-0.5), 1) < 0.27


def test_pair_correlation_requires_history_and_shrinks():
    idx = [f"g{i}" for i in range(100)]
    x = pd.Series(np.random.default_rng(1).normal(size=100), index=idx)
    r, n = pair_correlation(x, x)
    assert n == 100 and r == pytest.approx(100 / 130)
    assert pair_correlation(x.iloc[:MIN_SHARED_GAMES - 1], x) == (0.0, MIN_SHARED_GAMES - 1)


@pytest.fixture
def same_game_legs(session):
    day = et_date(utcnow())
    make_league(session, days=40, today=day)
    g = add_today_game(session, day)
    g.game_date = et_date(g.start_time)
    mv = add_production_model(session)
    add_injury_snapshot(session)
    add_odds(session, g.id, "100", 20.5, -110, -110)
    add_odds(session, g.id, "200", 10.5, -110, -110)
    run = AnalysisRun(run_type="test", target_date=g.game_date)
    session.add(run)
    session.flush()
    analyze_day(session, g.game_date, run, mv)
    return session.execute(select(Prediction)).scalars().all()


def test_same_game_parlay_withholds_ev_until_price_is_quoted(session, same_game_legs):
    ids = [p.id for p in same_game_legs]
    out = analyze_parlay(session, ids)
    assert out["status"] == "experimental" and out["price"] is None and out["ev"] is None
    assert any(w["code"] == "sgp_price_needed" for w in out["warnings"])
    assert out["joint_low"] <= out["joint_prob"] <= out["joint_high"]
    assert out["risk_level"] in ("elevated", "high", "very high")

    quoted = analyze_parlay(session, ids, quoted_price=200)
    assert quoted["price"]["source"] == "quoted"
    assert quoted["ev"] == pytest.approx(quoted["joint_prob"] * 3.0 - 1)


def test_rejects_bad_parlays(session, same_game_legs):
    with pytest.raises(ValueError, match="2 to"):
        analyze_parlay(session, [same_game_legs[0].id])
    with pytest.raises(ValueError, match="twice"):
        analyze_parlay(session, [same_game_legs[0].id, same_game_legs[0].id])
    with pytest.raises(ValueError, match="American"):
        analyze_parlay(session, [p.id for p in same_game_legs], quoted_price=50)


def test_analysis_writes_nothing(session, same_game_legs):
    before = {p.id: (p.model_prob, p.status, p.published) for p in same_game_legs}
    analyze_parlay(session, [p.id for p in same_game_legs])
    assert not session.new and not session.dirty
    assert before == {p.id: (p.model_prob, p.status, p.published) for p in same_game_legs}
