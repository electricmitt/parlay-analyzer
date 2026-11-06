"""Odds API credit budget: which runs are scheduled, and the credit reserve."""
from apscheduler.schedulers.background import BackgroundScheduler

from courtside.config import get_settings
from courtside.models import utcnow
from courtside.providers.odds_api import OddsEvent
from courtside.services.ingest import et_date, ingest_odds_api
from courtside.services.scheduler import build_scheduler

from .conftest import add_today_game, make_league


def _job_ids(monkeypatch, runs):
    monkeypatch.setattr(get_settings(), "odds_fetch_runs", runs)
    return {j.id for j in build_scheduler(BackgroundScheduler).get_jobs()}


def test_free_tier_schedule_drops_runs_without_fresh_odds(monkeypatch):
    ids = _job_ids(monkeypatch, "morning,pretip")
    assert {"morning", "pretip_digest", "grading_night"} <= ids
    assert "afternoon" not in ids and "pregame" not in ids
    assert {"afternoon", "pregame"} <= _job_ids(monkeypatch, "morning,afternoon,pregame,pretip")


class FakeClient:
    def __init__(self, game, remaining):
        self.remaining, self.calls = str(remaining), 0
        self._ev = OddsEvent(id="e1", commence_time=game.start_time,
                             home_team=game.home_team.name, away_team=game.away_team.name)

    def events(self):
        return [self._ev]

    def event_props(self, event_id):
        self.calls += 1
        return []


def test_credit_reserve_blocks_paid_calls(session, monkeypatch):
    today = et_date(utcnow())
    make_league(session, days=10, today=today)
    g = add_today_game(session, today)
    today = g.game_date = et_date(g.start_time)  # +5h can cross midnight ET
    session.flush()
    monkeypatch.setattr(get_settings(), "odds_api_min_credits", 20)

    low = FakeClient(g, remaining=20)
    out = ingest_odds_api(session, today, client=low)
    assert low.calls == 0 and out["skipped_budget"] == 1

    ok = FakeClient(g, remaining=300)
    out = ingest_odds_api(session, today, client=ok)
    assert ok.calls == 1 and out["events"] == 1 and out["skipped_budget"] == 0
