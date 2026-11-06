"""Agent 1 — NBA Data Intelligence: schedule, box scores, injuries, odds."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import ET, get_settings
from ..models import (
    Game, InjuryReport, OddsSnapshot, Player, PlayerGameStat, Team, audit, utcnow,
)
from ..names import match_player, norm_name, norm_team
from ..providers.espn import ESPNClient, GameRef, PlayerLine, ProviderError
from ..providers.odds_api import OddsAPIClient

log = logging.getLogger(__name__)


def et_date(utc_naive: dt.datetime) -> dt.date:
    return utc_naive.replace(tzinfo=dt.timezone.utc).astimezone(ET).date()


def today_et() -> dt.date:
    return dt.datetime.now(ET).date()


def _upsert_team(s: Session, t) -> None:
    team = s.get(Team, t.id)
    if team is None:
        s.add(Team(id=t.id, abbr=t.abbr, name=t.name))
    else:
        team.abbr, team.name = t.abbr, t.name


def upsert_game(s: Session, g: GameRef) -> Game:
    _upsert_team(s, g.home)
    _upsert_team(s, g.away)
    s.flush()
    game = s.get(Game, g.id)
    if game is None:
        game = Game(id=g.id)
        s.add(game)
    game.game_date = et_date(g.start_time)
    game.start_time = g.start_time
    game.season = g.season
    game.season_type = g.season_type
    game.home_team_id = g.home.id
    game.away_team_id = g.away.id
    game.status = g.status
    game.home_score = g.home_score
    game.away_score = g.away_score
    return game


def ingest_schedule(s: Session, day: dt.date, espn: ESPNClient | None = None) -> list[Game]:
    espn = espn or ESPNClient()
    games = [upsert_game(s, g) for g in espn.scoreboard(day)]
    # ESPN's "dates" param is ET-based; keep only games whose ET date matches.
    games = [g for g in games if g.game_date == day]
    audit(s, "data_agent", "ingest_schedule", date=day, games=len(games))
    return games


def store_box_score(s: Session, game: Game, lines: Iterable[PlayerLine]) -> int:
    n = 0
    now = utcnow()
    for ln in lines:
        p = s.get(Player, ln.player_id)
        if p is None:
            p = Player(id=ln.player_id, name=ln.name, norm_name=norm_name(ln.name))
            s.add(p)
        p.position = ln.position or p.position
        # Team assignment follows the most recent game seen.
        if p.team_id is None or _is_latest(s, ln.player_id, game):
            p.team_id = ln.team_id
        opp = game.away_team_id if ln.team_id == game.home_team_id else game.home_team_id
        row = s.get(PlayerGameStat, (game.id, ln.player_id))
        if row is None:
            row = PlayerGameStat(game_id=game.id, player_id=ln.player_id)
            s.add(row)
        row.team_id = ln.team_id
        row.opponent_id = opp
        row.game_date = game.game_date
        row.is_home = ln.team_id == game.home_team_id
        row.starter = ln.starter
        row.dnp = ln.dnp
        row.fetched_at = now
        row.source = "espn"
        for k in ("minutes", "pts", "reb", "ast", "fg3m", "fg3a", "fgm", "fga", "ftm", "fta",
                  "stl", "blk", "tov", "oreb", "dreb", "pf", "plus_minus"):
            setattr(row, k, ln.stats.get(k, 0 if k != "plus_minus" else None))
        n += 1
    return n


def _is_latest(s: Session, player_id: str, game: Game) -> bool:
    latest = s.execute(
        select(PlayerGameStat.game_date).where(PlayerGameStat.player_id == player_id)
        .order_by(PlayerGameStat.game_date.desc()).limit(1)
    ).scalar()
    return latest is None or game.game_date >= latest


def ingest_box_scores(s: Session, games: Iterable[Game], espn: ESPNClient | None = None,
                      force: bool = False) -> dict[str, int]:
    espn = espn or ESPNClient()
    out = {"loaded": 0, "skipped": 0, "errors": 0}
    for g in games:
        if g.box_loaded and not force:
            out["skipped"] += 1
            continue
        if g.season_type not in (2, 3) or g.status != "STATUS_FINAL":
            out["skipped"] += 1
            continue
        try:
            status, lines = espn.box_score(g.id)
        except (ProviderError, KeyError, ValueError) as e:
            log.warning("box score %s failed: %s", g.id, e)
            out["errors"] += 1
            audit(s, "data_agent", "box_score_error", game_id=g.id, error=str(e))
            continue
        if status != "STATUS_FINAL" or not lines:
            out["skipped"] += 1
            continue
        store_box_score(s, g, lines)
        g.box_loaded = True
        out["loaded"] += 1
        s.flush()
    return out


def backfill(s: Session, start: dt.date, end: dt.date, espn: ESPNClient | None = None,
             progress=None) -> dict[str, int]:
    espn = espn or ESPNClient()
    totals = {"days": 0, "games": 0, "loaded": 0, "errors": 0}
    day = start
    while day <= end:
        try:
            games = ingest_schedule(s, day, espn)
        except (ProviderError, KeyError, ValueError) as e:
            log.warning("schedule %s failed: %s", day, e)
            totals["errors"] += 1
            day += dt.timedelta(days=1)
            continue
        r = ingest_box_scores(s, games, espn)
        s.commit()
        totals["days"] += 1
        totals["games"] += len(games)
        totals["loaded"] += r["loaded"]
        totals["errors"] += r["errors"]
        if progress:
            progress(day, totals)
        day += dt.timedelta(days=1)
    return totals


# --------------------------------------------------------------------------- injuries
def ingest_injuries(s: Session, espn: ESPNClient | None = None) -> int:
    espn = espn or ESPNClient()
    rows = espn.injuries()
    now = utcnow()
    for r in rows:
        s.add(InjuryReport(player_id=r.player_id, player_name=r.player_name, team_id=r.team_id,
                           status=r.status, detail=r.detail, reported_at=r.reported_at,
                           fetched_at=now, source="espn"))
    audit(s, "data_agent", "ingest_injuries", count=len(rows))
    return len(rows)


def latest_injuries(s: Session, max_age_hours: int = 18) -> dict[str, InjuryReport]:
    """player_id -> injury row from the most recent snapshot (if fresh enough).
    A player missing from the latest snapshot is considered not on the report."""
    last = s.execute(select(InjuryReport.fetched_at).order_by(InjuryReport.fetched_at.desc()).limit(1)).scalar()
    if last is None or utcnow() - last > dt.timedelta(hours=max_age_hours):
        return {}
    rows = s.execute(select(InjuryReport).where(InjuryReport.fetched_at == last)).scalars()
    return {r.player_id: r for r in rows}


def injuries_fresh(s: Session, max_age_hours: int = 18) -> bool:
    last = s.execute(select(InjuryReport.fetched_at).order_by(InjuryReport.fetched_at.desc()).limit(1)).scalar()
    return last is not None and utcnow() - last <= dt.timedelta(hours=max_age_hours)


# --------------------------------------------------------------------------- odds
def team_roster(s: Session, team_id: str, before: dt.date, days: int = 45) -> dict[str, str]:
    """Players who appeared for the team recently (id -> name)."""
    since = before - dt.timedelta(days=days)
    rows = s.execute(
        select(Player.id, Player.name).join(PlayerGameStat, PlayerGameStat.player_id == Player.id)
        .where(PlayerGameStat.team_id == team_id, PlayerGameStat.game_date >= since,
               PlayerGameStat.game_date < before, Player.team_id == team_id)  # current team only
        .distinct()
    ).all()
    return {pid: name for pid, name in rows}


def ingest_odds_api(s: Session, day: dt.date, client: OddsAPIClient | None = None,
                    only_game_ids: list[str] | None = None) -> dict[str, int]:
    """Fetch props for the day's games (or a subset, to conserve API credits)."""
    client = client or OddsAPIClient()
    games = s.execute(select(Game).where(Game.game_date == day)).scalars().all()
    by_teams = {(norm_team(g.home_team.name), norm_team(g.away_team.name)): g for g in games}
    out = {"events": 0, "quotes": 0, "unmatched_players": 0, "unmatched_events": 0, "skipped_budget": 0,
           "failed_events": 0}
    now = utcnow()
    floor = get_settings().odds_api_min_credits
    for ev in client.events():  # listing events is free and reports the remaining balance
        g = by_teams.get((norm_team(ev.home_team), norm_team(ev.away_team)))
        if g is None or et_date(ev.commence_time) != day:
            if et_date(ev.commence_time) == day:
                out["unmatched_events"] += 1
            continue
        if only_game_ids is not None and g.id not in only_game_ids:
            continue
        if g.start_time <= now:
            continue  # never ingest pre-game odds for a game already under way
        if client.remaining is not None and int(float(client.remaining)) - 1 < floor:
            out["skipped_budget"] += 1  # credit reserve reached: keep the rest of the month's budget
            continue
        try:
            quotes = client.event_props(ev.id)
        except ProviderError as e:  # one bad game must not cost us the odds for the others
            log.warning("odds unavailable for game %s: %s", g.id, e)
            out["failed_events"] += 1
            continue
        out["events"] += 1
        candidates = {**team_roster(s, g.home_team_id, day), **team_roster(s, g.away_team_id, day)}
        for q in quotes:
            pid = match_player(q.player_name, candidates)
            if pid is None:
                out["unmatched_players"] += 1
            s.add(OddsSnapshot(game_id=g.id, player_id=pid, player_name_raw=q.player_name,
                               market=q.market, book=q.book, line=q.line, over_price=q.over_price,
                               under_price=q.under_price, source="the-odds-api",
                               book_last_update=q.book_last_update, fetched_at=now))
            out["quotes"] += 1
    audit(s, "data_agent", "ingest_odds", date=day, credits_remaining=client.remaining, **out)
    return out


def add_manual_odds(s: Session, game_id: str, player_id: str, market: str, book: str, line: float,
                    over_price: int | None, under_price: int | None) -> OddsSnapshot:
    game = s.get(Game, game_id)
    player = s.get(Player, player_id)
    if game is None or player is None:
        raise ValueError("unknown game or player")
    if game.start_time <= utcnow():
        raise ValueError("game has already started; pre-game odds can no longer be entered")
    if over_price is None and under_price is None:
        raise ValueError("at least one price is required")
    snap = OddsSnapshot(game_id=game_id, player_id=player_id, player_name_raw=player.name,
                        market=market, book=book, line=line, over_price=over_price,
                        under_price=under_price, source="manual", fetched_at=utcnow())
    s.add(snap)
    audit(s, "api", "manual_odds", game_id=game_id, player_id=player_id, market=market, book=book,
          line=line, over=over_price, under=under_price)
    return snap


def latest_odds(s: Session, game_ids: list[str]) -> list[OddsSnapshot]:
    """Most recent snapshot per (game, player, market, book)."""
    rows = s.execute(
        select(OddsSnapshot).where(OddsSnapshot.game_id.in_(game_ids), OddsSnapshot.player_id.is_not(None))
        .order_by(OddsSnapshot.fetched_at.desc(), OddsSnapshot.id.desc())
    ).scalars().all()
    seen: set[tuple] = set()
    out = []
    for r in rows:
        k = (r.game_id, r.player_id, r.market, r.book)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def settings_markets() -> list[str]:
    return [m.strip() for m in get_settings().odds_api_markets.split(",") if m.strip()]
