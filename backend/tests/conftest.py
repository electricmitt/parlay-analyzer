"""Test fixtures. All data here is SYNTHETIC and exists only inside temporary databases."""
from __future__ import annotations

import datetime as dt
import random

import pytest

from courtside import db as dbmod
from courtside.models import (
    Base, Game, InjuryReport, ModelVersion, OddsSnapshot, Player, PlayerGameStat, Team, utcnow,
)


@pytest.fixture()
def session(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    from courtside.config import get_settings
    get_settings.cache_clear()
    engine = dbmod.get_engine(url)
    Base.metadata.create_all(engine)
    s = dbmod.SessionLocal()
    yield s
    s.close()
    get_settings.cache_clear()


def make_league(s, days: int = 40, today: dt.date | None = None, seed: int = 1):
    """Two synthetic teams, 6 players each, playing each other every other day."""
    rng = random.Random(seed)
    today = today or dt.date.today()
    s.add_all([Team(id="1", abbr="AAA", name="Alpha Testers"), Team(id="2", abbr="BBB", name="Beta Testers")])
    s.flush()
    players = []
    for t in ("1", "2"):
        for i in range(6):
            pid = f"{t}{i:02d}"
            players.append(Player(id=pid, name=f"Test Player {pid}", norm_name=f"test player {pid}",
                                  position="G" if i < 3 else "F", team_id=t))
    s.add_all(players)
    s.flush()
    gnum = 0
    for d in range(days, 0, -2):
        day = today - dt.timedelta(days=d)
        gnum += 1
        g = Game(id=f"g{gnum}", game_date=day, start_time=dt.datetime.combine(day, dt.time(23, 0)), season=2027,
                 season_type=2, home_team_id="1" if gnum % 2 else "2", away_team_id="2" if gnum % 2 else "1",
                 status="STATUS_FINAL", home_score=110, away_score=105, box_loaded=True)
        s.add(g)
        for p in players:
            mins = max(0.0, rng.gauss(32 if p.id.endswith(("00", "01")) else 20, 3))
            s.add(PlayerGameStat(
                game_id=g.id, player_id=p.id, team_id=p.team_id, opponent_id="2" if p.team_id == "1" else "1",
                game_date=day, is_home=(p.team_id == g.home_team_id), starter=mins > 25, dnp=False, minutes=mins,
                pts=int(mins * 0.7 + rng.gauss(0, 4)) if mins else 0, reb=int(mins * 0.2), ast=int(mins * 0.15),
                fg3m=int(mins * 0.06), fga=int(mins * 0.5), fgm=int(mins * 0.24), pf=2))
    s.flush()
    return players


def add_today_game(s, today: dt.date, hours_from_now: float = 5.0) -> Game:
    g = Game(id="today1", game_date=today, start_time=utcnow() + dt.timedelta(hours=hours_from_now), season=2027,
             season_type=2, home_team_id="1", away_team_id="2", status="STATUS_SCHEDULED")
    s.add(g)
    s.flush()
    return g


def add_production_model(s) -> ModelVersion:
    from courtside.modeling.baseline import BaselineParams
    from courtside.modeling.data import load_history
    from courtside.modeling.evaluate import fit_params
    hist = load_history(s)
    p = fit_params(hist, hist["game_date"].max() + dt.timedelta(days=1)) if len(hist) else BaselineParams()
    mv = ModelVersion(name=p.name, version="test", status="production", params=p.to_dict(), metrics={},
                      promoted_at=utcnow())
    s.add(mv)
    s.flush()
    return mv


def add_injury_snapshot(s, entries: list[tuple[str, str]] | None = None):
    now = utcnow()
    entries = entries or [("299", "Out")]  # an unrelated player so the snapshot is non-empty
    for pid, status in entries:
        s.add(InjuryReport(player_id=pid, player_name=pid, team_id="1", status=status, fetched_at=now))
    s.flush()


def add_odds(s, game_id: str, player_id: str, line: float, over: int, under: int, book="hardrockbet",
             market="pts", age_min: float = 0) -> OddsSnapshot:
    sn = OddsSnapshot(game_id=game_id, player_id=player_id, player_name_raw=player_id, market=market, book=book,
                      line=line, over_price=over, under_price=under, source="manual",
                      fetched_at=utcnow() - dt.timedelta(minutes=age_min))
    s.add(sn)
    s.flush()
    return sn
