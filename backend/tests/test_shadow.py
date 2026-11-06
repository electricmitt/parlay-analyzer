"""The shadow report may only use odds captured before tip-off, and must write nothing."""
import datetime as dt

from sqlalchemy import func, select

from courtside.models import Game, ModelVersion, OddsSnapshot, PlayerGameStat, Prediction
from courtside.services.shadow import pretip_quotes, shadow_report

from .conftest import add_production_model, make_league


def _final_game(session):
    make_league(session, days=40, today=dt.date(2026, 11, 4))
    add_production_model(session)
    g = session.execute(select(Game).order_by(Game.game_date.desc())).scalars().first()
    g.status = "STATUS_FINAL"
    g.start_time = dt.datetime(2026, 11, 1, 0, 0)
    session.flush()
    return g


def _quote(session, g, player, line, minutes_before, over=-110, under=-110, book="draftkings"):
    session.add(OddsSnapshot(game_id=g.id, player_id=player, player_name_raw=player, market="pts", book=book, line=line,
                             over_price=over, under_price=under, source="manual",
                             fetched_at=g.start_time - dt.timedelta(minutes=minutes_before)))
    session.flush()


def test_uses_latest_quote_before_tip_and_ignores_later_ones(session):
    g = _final_game(session)
    _quote(session, g, "100", 10.5, 300)
    _quote(session, g, "100", 11.5, 30)
    _quote(session, g, "100", 99.5, -30)  # after tip-off
    _quote(session, g, "101", 8.5, 300, book="fanduel")  # left over from an earlier pull
    q = pretip_quotes(session, g.game_date, g.game_date)
    assert q.line.tolist() == [11.5]


def test_report_scores_both_models_and_writes_nothing(session):
    g = _final_game(session)
    players = session.execute(select(PlayerGameStat).where(PlayerGameStat.game_id == g.id,
                                                           PlayerGameStat.minutes > 0)).scalars().all()
    for r in players:
        _quote(session, g, r.player_id, r.pts + 0.5, 30)
    before = session.execute(select(func.count(Prediction.id))).scalar()
    out = shadow_report(session, g.game_date, g.game_date)
    assert out["nights"] == 1 and out["candidate_changes"] == {"shrink_minutes": 0.0}
    for name in ("production", "candidate"):
        assert out[name]["props"] > 0 and "w1" in out[name]
    assert session.execute(select(func.count(Prediction.id))).scalar() == before
    prod = session.execute(select(ModelVersion).where(ModelVersion.status == "production")).scalars().one()
    assert prod.params["shrink_minutes"] != 0.0


def test_no_odds_reports_it_plainly(session):
    g = _final_game(session)
    assert "error" in shadow_report(session, g.game_date, g.game_date)
