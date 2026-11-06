"""A bad odds response or a sleeping Mac must not erase picks, spam Telegram or lose a run."""
import datetime as dt

import httpx
import pytest
from sqlalchemy import select, update

from courtside.config import ET, get_settings
from courtside.models import AnalysisRun, OddsSnapshot, PlayerGameStat, Prediction, PredictionEvent, utcnow
from courtside.providers import odds_api
from courtside.providers.espn import ProviderError
from courtside.providers.odds_api import OddsAPIClient, OddsEvent
from courtside.services import orchestrator, scheduler
from courtside.services.analysis import analyze_day
from courtside.services.digest import build_digest
from courtside.services.ingest import ingest_odds_api

from .conftest import add_injury_snapshot, add_odds
from .test_digest import _slate

SECRET = "not-a-real-key"


def _client(responses, monkeypatch):
    monkeypatch.setattr(odds_api.time, "sleep", lambda _: None)
    seq = iter(responses)

    def handler(_req):
        r = next(seq)
        if isinstance(r, Exception):
            raise r
        return httpx.Response(r, json=[], headers={"x-requests-remaining": "400"})
    return OddsAPIClient(api_key=SECRET, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_temporary_odds_errors_are_retried(monkeypatch):
    assert _client([502, 503, 200], monkeypatch).events() == []


def test_network_error_becomes_provider_error_without_the_key(monkeypatch):
    with pytest.raises(ProviderError) as e:
        _client([httpx.ConnectError(f"apiKey={SECRET}")] * 3, monkeypatch).events()
    assert SECRET not in str(e.value)


def test_permanent_errors_are_not_retried(monkeypatch):
    with pytest.raises(ProviderError):  # a second response would raise StopIteration instead
        _client([401], monkeypatch).events()


def test_one_failed_game_keeps_the_others(session):
    _, g, _ = _slate(session)

    class Flaky:
        remaining = "400"

        def events(self):
            ev = dict(commence_time=g.start_time, home_team=g.home_team.name, away_team=g.away_team.name)
            return [OddsEvent(id="bad", **ev), OddsEvent(id="good", **ev)]

        def event_props(self, event_id):
            if event_id == "bad":
                raise ProviderError("HTTP 502")
            return []

    out = ingest_odds_api(session, g.game_date, client=Flaky())
    assert out["failed_events"] == 1 and out["events"] == 1


def _publish_one(session):
    today, g, mv = _slate(session)
    rows = session.execute(select(PlayerGameStat).where(PlayerGameStat.player_id == "100")).scalars().all()
    line = round(sum(r.pts for r in rows) / len(rows)) - 1.5
    add_odds(session, g.id, "100", line, 105, -125)
    add_odds(session, g.id, "100", line, -115, -105, book="draftkings")
    res = _run(session, today, mv)
    assert res["recommended"] == 1
    pick = session.execute(select(Prediction).where(Prediction.published.is_(True))).scalars().one()
    return today, mv, pick


def _run(session, today, mv):
    run = AnalysisRun(run_type="test", target_date=today)
    session.add(run)
    session.flush()
    return analyze_day(session, today, run, mv)


def _age_odds(session):
    session.execute(update(OddsSnapshot).values(fetched_at=utcnow() - dt.timedelta(hours=9)))
    session.flush()


@pytest.fixture(autouse=True)
def model_only(monkeypatch):
    monkeypatch.setattr(get_settings(), "market_blend_weight", 1.0)


def test_failed_refresh_keeps_the_pick_and_says_so(session):
    today, mv, pick = _publish_one(session)
    _age_odds(session)
    res = _run(session, today, mv)
    assert res["withdrawn"] == 0 and res["kept_unverified"] == 1
    assert session.get(Prediction, pick.id).status == "active"
    events = [e.event for e in session.execute(select(PredictionEvent).where(
        PredictionEvent.prediction_id == pick.id)).scalars()]
    assert "unverified" in events
    _, body = build_digest(session, today, "pretip")
    assert "Test Player 100 OVER" in body and "could not be refreshed" in body and "WITHDRAWN" not in body


def test_failed_refresh_still_withdraws_on_worse_availability(session):
    today, mv, pick = _publish_one(session)
    _age_odds(session)
    add_injury_snapshot(session, [("100", "Questionable")])
    assert _run(session, today, mv)["withdrawn"] == 1
    assert session.get(Prediction, pick.id).status == "withdrawn"


def test_digest_does_not_call_a_feed_failure_a_pass(session):
    today, g, mv = _slate(session)
    add_odds(session, g.id, "100", 40.5, -110, -110)
    _age_odds(session)
    _run(session, today, mv)
    _, body = build_digest(session, today, "pretip")
    assert "NO EVALUATION" in body and "PASS —" not in body


def test_withdrawals_are_one_message_per_run(session, monkeypatch):
    today, mv, pick = _publish_one(session)
    sent = []
    monkeypatch.setattr(orchestrator, "notify", lambda _s, key, kind, title, body: sent.append((key, kind, title, body)))
    orchestrator._notify_run(session, {"_withdrawn_ids": [pick.id, pick.id]}, 7)
    assert len(sent) == 1
    key, kind, title, body = sent[0]
    assert key == "withdrawn-run-7" and kind == "withdrawal" and title.startswith("WITHDRAWN: 2")
    assert body.count("Test Player 100") == 2


NOW = dt.datetime(2026, 11, 5, 15, 47)  # 10:47 AM ET, naive UTC
NOW_ET = NOW.replace(tzinfo=dt.timezone.utc).astimezone(ET)


@pytest.mark.parametrize("now_et,tip_hours,sent,due", [
    (NOW_ET, 10.0, False, True),                              # woke after a missed 9:00, games tonight
    (NOW_ET, 10.0, True, False),                              # already ran
    (NOW_ET.replace(hour=9, minute=5), 10.0, False, False),   # the scheduled job is still handling it
    (NOW_ET, 0.25, False, False),                             # the pre-tip run covers it
    (NOW_ET, -1.0, False, False),                             # games have begun
    (NOW_ET, None, False, True),                              # schedule not loaded yet
    (NOW_ET.replace(hour=19), None, False, False),            # too late to guess without a schedule
])
def test_morning_catchup_due(now_et, tip_hours, sent, due):
    tip = None if tip_hours is None else NOW + dt.timedelta(hours=tip_hours)
    assert scheduler.morning_catchup_due(now_et, tip, NOW, 30, sent) is due


def test_morning_job_cannot_run_twice_at_once(monkeypatch):
    monkeypatch.setattr(scheduler, "run_analysis", lambda **_: pytest.fail("ran while already running"))
    with scheduler._morning_lock:
        scheduler.morning_job()


def test_scheduler_has_catchup_job():
    from apscheduler.schedulers.background import BackgroundScheduler
    ids = {j.id for j in scheduler.build_scheduler(BackgroundScheduler).get_jobs()}
    assert "catchup" in ids
