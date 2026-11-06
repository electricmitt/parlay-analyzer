import datetime as dt

from sqlalchemy import select

from courtside.models import AnalysisRun, Notification, utcnow
from courtside.services import notify as notify_mod
from courtside.services.analysis import analyze_day
from courtside.services.digest import build_digest, send_digest
from courtside.services.ingest import et_date
from courtside.services.scheduler import pretip_due

from .conftest import add_injury_snapshot, add_odds, add_production_model, add_today_game, make_league


def test_split_message_respects_limit():
    text = "\n".join(f"line {i} " + "x" * 50 for i in range(300))
    chunks = notify_mod.split_message(text, limit=1000)
    assert all(len(c) <= 1000 for c in chunks)
    assert "\n".join(chunks).replace("\n", "") == text.replace("\n", "")


def test_routing_by_kind():
    assert notify_mod._wants("digest,withdrawal", "digest")
    assert not notify_mod._wants("digest,withdrawal", "recommendation")
    assert notify_mod._wants("all", "anything")


def test_pretip_due_window():
    now = dt.datetime(2026, 11, 2, 23, 0)
    assert pretip_due(now + dt.timedelta(minutes=25), now, 30, False)
    assert not pretip_due(now + dt.timedelta(minutes=45), now, 30, False)
    assert not pretip_due(now + dt.timedelta(minutes=25), now, 30, True)   # already sent
    assert not pretip_due(now - dt.timedelta(minutes=5), now, 30, False)   # game started
    assert not pretip_due(None, now, 30, False)


def _slate(session):
    today = et_date(utcnow())
    make_league(session, days=40, today=today)
    g = add_today_game(session, today)
    mv = add_production_model(session)
    add_injury_snapshot(session)
    return today, g, mv


def test_digest_without_model_says_no_recommendations(session):
    today = et_date(utcnow())
    make_league(session, days=20, today=today)
    add_today_game(session, today)
    title, body = build_digest(session, today, "morning")
    assert "NO recommendations" in body and "Morning" in title


def test_digest_pass_and_dedupe(session, monkeypatch):
    sent = []
    monkeypatch.setattr(notify_mod, "send_telegram", lambda text: sent.append(text) or True)
    from courtside.config import get_settings
    st = get_settings()
    monkeypatch.setattr(st, "telegram_bot_token", "t")
    monkeypatch.setattr(st, "telegram_chat_id", "1")
    today, g, mv = _slate(session)
    add_odds(session, g.id, "100", 12.5, 100, -120)  # blocked by the market-gap guard -> PASS
    run = AnalysisRun(run_type="test", target_date=today)
    session.add(run)
    session.flush()
    analyze_day(session, today, run, mv)
    r1 = send_digest(session, today, "morning")
    r2 = send_digest(session, today, "morning")
    assert r1["sent"] and not r2["sent"]  # once per day per kind
    assert len(sent) == 1 and "PASS" in sent[0]
    assert session.execute(select(Notification).where(Notification.kind == "digest")).scalars().one()


def test_digest_lists_published_pick_and_withdrawal(session):
    from courtside.models import PlayerGameStat
    today, g, mv = _slate(session)
    rows = session.execute(select(PlayerGameStat).where(PlayerGameStat.player_id == "100")).scalars().all()
    line = round(sum(r.pts for r in rows) / len(rows)) - 1.5
    add_odds(session, g.id, "100", line, 105, -125)
    add_odds(session, g.id, "100", line, -115, -105, book="draftkings")
    run = AnalysisRun(run_type="test", target_date=today)
    session.add(run)
    session.flush()
    res = analyze_day(session, today, run, mv)
    assert res["recommended"] == 1
    _, body = build_digest(session, today, "morning")
    assert "Test Player 100 OVER" in body and "Hard Rock +105" in body and "odds as of" in body
    add_injury_snapshot(session, [("100", "Questionable")])
    run2 = AnalysisRun(run_type="test", target_date=today)
    session.add(run2)
    session.flush()
    analyze_day(session, today, run2, mv)
    _, body = build_digest(session, today, "pretip")
    assert "WITHDRAWN" in body and "PASS" in body
