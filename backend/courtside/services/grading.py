"""Settle predictions against official final box scores.

Rules (standard US sportsbook player-prop rules; check your book's house rules):
* over/under vs the posted line; equal to an integer line -> push
* player does not play (DNP / not in box score) -> void
* game not final -> unresolved (left open)
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Game, OddsSnapshot, PlayerGameStat, Prediction, PredictionEvent, audit, utcnow
from ..modeling.baseline import market_components
from .learning import attribute_error


def settle_one(pred: Prediction, row: PlayerGameStat | None) -> tuple[str, float | None, float | None]:
    if row is None or row.dnp or (row.minutes or 0) <= 0:
        return "void", None, None
    actual = float(sum(getattr(row, c) for c in market_components(pred.market)))
    if actual == pred.line:
        res = "push"
    elif (actual > pred.line) == (pred.side == "over"):
        res = "win"
    else:
        res = "loss"
    return res, actual, float(row.minutes)


def closing_snapshot(s: Session, pred: Prediction, game: Game) -> OddsSnapshot | None:
    return s.execute(
        select(OddsSnapshot).where(OddsSnapshot.game_id == pred.game_id, OddsSnapshot.player_id == pred.player_id,
                                   OddsSnapshot.market == pred.market, OddsSnapshot.book == pred.book,
                                   OddsSnapshot.fetched_at < game.start_time)
        .order_by(OddsSnapshot.fetched_at.desc()).limit(1)
    ).scalars().first()


def grade_games(s: Session, games: list[Game]) -> dict[str, int]:
    out = {"settled": 0, "win": 0, "loss": 0, "push": 0, "void": 0, "unresolved": 0}
    for g in games:
        preds = s.execute(select(Prediction).where(Prediction.game_id == g.id, Prediction.result.is_(None))).scalars().all()
        if not preds:
            continue
        if not (g.is_final and g.box_loaded):
            out["unresolved"] += len(preds)
            continue
        for p in preds:
            row = s.get(PlayerGameStat, (g.id, p.player_id))
            res, actual, mins = settle_one(p, row)
            p.result, p.actual, p.actual_minutes, p.settled_at = res, actual, mins, utcnow()
            p.error_tags = attribute_error(p, mins, actual, row, g)
            close = closing_snapshot(s, p, g)
            if close is not None:
                p.closing_line = close.line
                p.closing_price = close.over_price if p.side == "over" else close.under_price
            if p.status == "active":
                p.status = "locked"
            s.add(PredictionEvent(prediction_id=p.id, event="settled",
                                  detail={"result": res, "actual": actual, "minutes": mins}))
            out["settled"] += 1
            out[res] += 1
    audit(s, "grading_agent", "grade_games", games=len(games), **out)
    return out
