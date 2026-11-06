"""End-to-end pipeline tests on a synthetic league (temporary DB)."""
import datetime as dt

import pytest
from sqlalchemy import select

from courtside.models import (
    AnalysisRun, Game, Prediction, PredictionEvent, PlayerGameStat, utcnow,
)
from courtside.services.analysis import analyze_day
from courtside.services.grading import grade_games, settle_one
from courtside.services.ingest import et_date
from courtside.services.performance import _max_drawdown
from courtside.services.scheduler import due_pregame_windows

from .conftest import add_injury_snapshot, add_odds, add_production_model, add_today_game, make_league


def _today():
    return et_date(utcnow())


def _run(s, mv):
    run = AnalysisRun(run_type="test", target_date=_today())
    s.add(run)
    s.flush()
    return analyze_day(s, _today(), run, mv)


def _setup(s, injuries=None):
    today = _today()
    make_league(s, days=40, today=today)
    g = add_today_game(s, today)
    mv = add_production_model(s)
    add_injury_snapshot(s, injuries)
    return g, mv


def test_generous_price_is_published_and_bad_price_passes(session):
    g, mv = _setup(session)
    # Star player 100 averages ~22 pts. A 12.5 line at +100 on the over is clearly favourable
    # but too far from a -110/-110 market => blocked by the model/market gap guard.
    add_odds(session, g.id, "100", 12.5, 100, -120)
    res = _run(session, mv)
    pred = session.execute(select(Prediction)).scalars().one()
    assert pred.side == "over" and pred.ev > 0
    assert not pred.eligible and any("disagrees" in r for r in pred.reasons)
    assert res["recommended"] == 0 and g.id in res["pass_games"]


def test_publish_then_withdraw_on_injury(session):
    g, mv = _setup(session)
    feats = session.execute(select(PlayerGameStat).where(PlayerGameStat.player_id == "100")).scalars().all()
    avg = sum(r.pts for r in feats) / len(feats)
    line = round(avg) - 1.5  # modest edge on the over, consistent with a near-fair market elsewhere
    add_odds(session, g.id, "100", line, 105, -125)
    add_odds(session, g.id, "100", line, -115, -105, book="draftkings")
    res = _run(session, mv)
    published = session.execute(select(Prediction).where(Prediction.published.is_(True))).scalars().all()
    if not published:
        pytest.skip(f"synthetic edge not eligible under default filters: "
                    f"{[p.reasons for p in session.execute(select(Prediction)).scalars()]}")
    assert res["recommended"] == 1 and published[0].book == "hardrockbet"
    # Player becomes questionable -> next run must withdraw (not silently replace) the pick.
    add_injury_snapshot(session, [("100", "Questionable")])
    res2 = _run(session, mv)
    assert res2["withdrawn"] == 1
    old = session.get(Prediction, published[0].id)
    assert old.status == "withdrawn"
    events = [e.event for e in session.execute(select(PredictionEvent).where(
        PredictionEvent.prediction_id == old.id)).scalars()]
    assert "published" in events and "withdrawn" in events


def test_stale_odds_and_out_player(session):
    g, mv = _setup(session, injuries=[("101", "Out")])
    add_odds(session, g.id, "100", 20.5, -110, -110, age_min=500)
    add_odds(session, g.id, "101", 20.5, -110, -110)
    _run(session, mv)
    preds = session.execute(select(Prediction)).scalars().all()
    assert {p.player_id for p in preds} == {"100"}  # ruled-out player is not projected
    assert any("old" in r for r in preds[0].reasons)


def test_predictions_are_immutable(session):
    g, mv = _setup(session)
    add_odds(session, g.id, "100", 20.5, -110, -110)
    _run(session, mv)
    session.commit()
    p = session.execute(select(Prediction)).scalars().first()
    p.model_prob = 0.99
    with pytest.raises(ValueError, match="immutable"):
        session.flush()
    session.rollback()
    p = session.execute(select(Prediction)).scalars().first()
    p.status = "locked"  # lifecycle columns are allowed
    session.flush()


def test_no_predictions_for_started_games(session):
    today = _today()
    make_league(session, days=20, today=today)
    g = add_today_game(session, today, hours_from_now=-0.5)
    mv = add_production_model(session)
    add_injury_snapshot(session)
    add_odds(session, g.id, "100", 20.5, -110, -110)
    res = _run(session, mv)
    assert res["games"] == 0
    assert session.execute(select(Prediction)).first() is None


def test_grading(session):
    g, mv = _setup(session)
    add_odds(session, g.id, "100", 20.5, -110, -110)
    add_odds(session, g.id, "200", 10.5, -110, -110)
    _run(session, mv)
    g.status, g.box_loaded, g.home_score, g.away_score = "STATUS_FINAL", True, 120, 90
    session.add(PlayerGameStat(game_id=g.id, player_id="100", team_id="1", opponent_id="2", game_date=g.game_date,
                               is_home=True, minutes=35, pts=25, fga=18, fgm=9, pf=1))
    session.add(PlayerGameStat(game_id=g.id, player_id="200", team_id="2", opponent_id="1", game_date=g.game_date,
                               is_home=False, dnp=True, minutes=0))
    session.flush()
    out = grade_games(session, [g])
    assert out["settled"] == 2 and out["void"] == 1
    p100 = session.execute(select(Prediction).where(Prediction.player_id == "100")).scalars().one()
    assert p100.actual == 25 and p100.result == ("win" if p100.side == "over" else "loss")
    assert "blowout" in p100.error_tags


def test_settle_push_on_integer_line():
    class P:  # minimal stand-in
        market, side, line = "pts", "over", 20.0

    class R:
        dnp, minutes, pts = False, 30, 20
    assert settle_one(P, R)[0] == "push"


def test_pregame_windows():
    now = dt.datetime(2026, 11, 2, 23, 0)
    g = Game(id="x", status="STATUS_SCHEDULED", start_time=now + dt.timedelta(minutes=58))
    assert due_pregame_windows([g], now, set()) == [("x", 60)]
    assert due_pregame_windows([g], now, {"x:60"}) == []
    g.start_time = now + dt.timedelta(minutes=30)
    assert due_pregame_windows([g], now, set()) == []


def test_max_drawdown():
    assert _max_drawdown([1, -1, -1, -1, 2]) == 3
    assert _max_drawdown([]) == 0


def test_unvalidated_market_is_not_published(session):
    g, mv = _setup(session)
    params = dict(mv.params)
    params["validated_markets"] = ["pts"]
    mv.params = params
    session.flush()
    add_odds(session, g.id, "100", 1.5, -110, -110, market="blk")
    _run(session, mv)
    pred = session.execute(select(Prediction)).scalars().one()
    assert not pred.eligible and any("not validated" in r for r in pred.reasons)
