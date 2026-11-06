"""Daily digests pushed to Telegram/Discord: a morning digest and a pre-tip digest
(sent shortly before the first game of the slate). Plain text, no markdown, so nothing
needs escaping. Every pick shows the price and the time the odds were captured."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import ET, get_settings
from ..models import Game, Notification, OddsSnapshot, Player, Prediction, utcnow
from ..modeling.baseline import MARKET_LABELS
from ..odds_math import profit_units
from .learning import production_model
from .notify import notify

BOOK_NAMES = {"hardrockbet": "Hard Rock", "hardrockbet_fl": "Hard Rock", "draftkings": "DraftKings",
              "fanduel": "FanDuel", "betmgm": "BetMGM", "williamhill_us": "Caesars"}


def _price(a: int) -> str:
    return f"+{a}" if a > 0 else str(a)


def _et(t: dt.datetime | None, fmt: str = "%-I:%M %p") -> str:
    return "?" if t is None else t.replace(tzinfo=dt.timezone.utc).astimezone(ET).strftime(fmt) + " ET"


def first_tip(s: Session, day: dt.date) -> dt.datetime | None:
    return s.execute(select(Game.start_time).where(Game.game_date == day).order_by(Game.start_time)).scalars().first()


def _games_without_fresh_odds(s: Session, games: dict[str, Game]) -> list[str]:
    """Games not yet started whose newest odds are past the staleness limit (or missing)."""
    now = utcnow()
    limit = dt.timedelta(minutes=get_settings().max_odds_age_min)
    latest = dict(s.execute(select(OddsSnapshot.game_id, func.max(OddsSnapshot.fetched_at))
                            .where(OddsSnapshot.game_id.in_(list(games))).group_by(OddsSnapshot.game_id)).all())
    return [gid for gid, g in games.items()
            if g.start_time > now and (gid not in latest or now - latest[gid] > limit)]


def _pick_line(p: Prediction, player: Player, game: Game) -> str:
    book = BOOK_NAMES.get(p.book, p.book)
    stake = f" | stake {p.kelly_stake:g}u" if p.kelly_stake else ""
    est = "blend" if (p.data_quality or {}).get("market_blend") else "model"
    return (f"• {player.name} {p.side.upper()} {p.line:g} {MARKET_LABELS.get(p.market, p.market)}\n"
            f"  {book} {_price(p.price)} | {est} {p.model_prob:.0%} | fair {_price(p.fair_odds)} | EV {p.ev:+.1%}{stake}\n"
            f"  proj {p.proj_mean:.1f} (80%: {p.proj_p10:.0f}–{p.proj_p90:.0f}) | "
            f"{game.away_team.abbr} @ {game.home_team.abbr} {_et(game.start_time)} | odds as of {_et(p.odds_fetched_at)}")


def build_digest(s: Session, day: dt.date, kind: str) -> tuple[str, str]:
    """kind: 'morning' | 'pretip'. Returns (title, body)."""
    games = {g.id: g for g in s.execute(select(Game).where(Game.game_date == day).order_by(Game.start_time)).scalars()}
    label = "Morning" if kind == "morning" else "Pre-tip"
    title = f"Courtside AI — {label} digest {day:%a %b %-d}"
    lines: list[str] = []
    if not games:
        return title, "No NBA games today."
    tip = min(g.start_time for g in games.values())
    lines.append(f"{len(games)} games · first tip {_et(tip)}")

    mv = production_model(s)
    preds = s.execute(select(Prediction).where(Prediction.game_id.in_(list(games)),
                                               Prediction.status.in_(["active", "locked"]))).scalars().all()
    picks = sorted([p for p in preds if p.published], key=lambda p: p.ev, reverse=True)
    stale = _games_without_fresh_odds(s, games)
    if mv is None:
        lines.append("")
        lines.append("No model has passed validation yet, so there are NO recommendations today "
                     f"({len(preds)} props analysed on paper only).")
    elif not preds:
        lines.append("")
        lines.append("No prop odds available yet (no odds feed or manual entries) — nothing to evaluate.")
    elif not picks and len(stale) == len(games):
        lines.append("")
        lines.append(f"NO EVALUATION — odds could not be refreshed for any of the {len(games)} games. "
                     "This is a feed problem, not a PASS on the slate.")
    elif not picks:
        lines.append("")
        lines.append(f"PASS — none of the {len(preds)} props evaluated met every filter. No qualifying opportunity.")
    else:
        since = _last_digest_time(s, day, "morning") if kind == "pretip" else None
        lines.append(f"{len(picks)} pick(s) from {len(preds)} props evaluated · model {mv.name} {mv.version}")
        blend = next(((p.data_quality or {}).get("market_blend") for p in picks
                      if (p.data_quality or {}).get("market_blend")), None)
        if blend:
            lines.append(f"Provisional safeguard: estimates are {blend['weight']:.0%} model, "
                         f"{1 - blend['weight']:.0%} no-vig market. The weight is an assumption, "
                         "not yet tested on real lines.")
        lines.append("")
        if stale:
            lines.append(f"Odds could not be refreshed for {len(stale)} game(s). Picks there use the older "
                         "prices shown, so check the current line first.")
        for p in picks:
            tag = "NEW " if since and p.created_at > since and not _was_published_before(s, p, since) else ""
            if tag:
                lines.append("[NEW since morning]")
            lines.append(_pick_line(p, s.get(Player, p.player_id), games[p.game_id]))

    withdrawn = s.execute(select(Prediction).where(Prediction.game_id.in_(list(games)),
                                                   Prediction.status == "withdrawn")).scalars().all()
    current = {(p.game_id, p.player_id, p.market, p.side) for p in picks}
    withdrawn = [p for p in withdrawn if (p.game_id, p.player_id, p.market, p.side) not in current]
    if withdrawn:
        lines.append("")
        lines.append("WITHDRAWN (no longer meets filters — reconsider if you acted on these):")
        for p in withdrawn:
            pl = s.get(Player, p.player_id)
            lines.append(f"• {pl.name} {p.side.upper()} {p.line:g} {MARKET_LABELS.get(p.market, p.market)} "
                         f"({BOOK_NAMES.get(p.book, p.book)} {_price(p.price)})")

    if kind == "morning":
        lines.extend(_yesterday(s, day))
    lines.append("")
    lines.append("Model estimates, not guarantees. Positive EV loses often in the short run. "
                 "Recommendations only — nothing is wagered for you.")
    return title, "\n".join(lines)


def _was_published_before(s: Session, p: Prediction, since: dt.datetime) -> bool:
    """True if the same pick (player/market/side/line) was already published before `since`."""
    return s.execute(select(Prediction.id).where(
        Prediction.game_id == p.game_id, Prediction.player_id == p.player_id, Prediction.market == p.market,
        Prediction.side == p.side, Prediction.line == p.line, Prediction.published.is_(True),
        Prediction.created_at <= since)).first() is not None


def _last_digest_time(s: Session, day: dt.date, kind: str) -> dt.datetime | None:
    return s.execute(select(Notification.created_at).where(
        Notification.dedupe_key == f"digest-{kind}-{day}")).scalars().first()


def _yesterday(s: Session, day: dt.date) -> list[str]:
    y = day - dt.timedelta(days=1)
    ids = [g for (g,) in s.execute(select(Game.id).where(Game.game_date == y))]
    if not ids:
        return []
    done = [p for p in s.execute(select(Prediction).where(
        Prediction.game_id.in_(ids), Prediction.published.is_(True),
        Prediction.status.in_(["locked", "active"]), Prediction.result.is_not(None))).scalars()]
    if not done:
        return []
    w = sum(p.result == "win" for p in done)
    l = sum(p.result == "loss" for p in done)
    pu = sum(p.result == "push" for p in done)
    units = sum(profit_units(p.result, p.price) for p in done)
    out = ["", f"Yesterday: {w}-{l}-{pu} ({units:+.2f}u at 1u flat)"]
    for p in done:
        pl = s.get(Player, p.player_id)
        out.append(f"• {p.result.upper()}: {pl.name} {p.side} {p.line:g} {MARKET_LABELS.get(p.market, p.market)}"
                   f" — actual {p.actual:g}" if p.actual is not None else f"• {p.result.upper()}: {pl.name}")
    return out


def send_digest(s: Session, day: dt.date, kind: str, force: bool = False) -> dict:
    title, body = build_digest(s, day, kind)
    key = f"digest-{kind}-{day}" + (f"-forced-{utcnow():%H%M%S}" if force else "")
    n = notify(s, key, "digest", title, body)
    return {"sent": n is not None, "delivered": n.delivered if n else "already sent today", "title": title,
            "telegram_configured": bool(get_settings().telegram_bot_token and get_settings().telegram_chat_id)}
