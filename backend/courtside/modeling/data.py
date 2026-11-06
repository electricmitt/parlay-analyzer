from __future__ import annotations

import datetime as dt

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Game, Player, PlayerGameStat
from .baseline import STAT_COLS

_JOINED = {"position", "season", "season_type"}


def load_history(s: Session, before: dt.date | None = None, since: dt.date | None = None) -> pd.DataFrame:
    """Regular-season + playoff player box scores strictly before `before`."""
    q = (select(PlayerGameStat, Player.position, Game.season, Game.season_type)
         .join(Player, Player.id == PlayerGameStat.player_id)
         .join(Game, Game.id == PlayerGameStat.game_id)
         .where(Game.season_type.in_([2, 3])))
    if before is not None:
        q = q.where(PlayerGameStat.game_date < before)
    if since is not None:
        q = q.where(PlayerGameStat.game_date >= since)
    rows = []
    for st, pos, season, season_type in s.execute(q):
        d = {c: getattr(st, c) for c in STAT_COLS if c not in _JOINED}
        d["position"], d["season"], d["season_type"] = pos, season, season_type
        rows.append(d)
    df = pd.DataFrame(rows, columns=STAT_COLS)
    if len(df):
        df["game_date"] = pd.to_datetime(df["game_date"]).dt.date
    return df.sort_values(["game_date", "game_id"]).reset_index(drop=True)
