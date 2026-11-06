"""Daily autonomous workflow (America/New_York).

  09:00  morning analysis (schedule, stats, injuries, odds, projections) -> morning digest
  ~T-30  before the FIRST game: refresh analysis -> pre-tip digest (PRETIP_DIGEST_MINUTES)
  13:00  afternoon analysis (refresh injuries/odds, recompute, preliminary picks)
  every 5 min  pre-game check: re-run analysis ~60 and ~15 min before each tip-off
  every 30 min 22:00-02:00 + 09:30  grading of finished games
  every 5 min  wake-up check: run a missed morning analysis if the Mac was asleep at 09:00
  Mon 05:00 weekly walk-forward evaluation -> registers a *candidate* model only.
             Promotion is a human-approved step after shadow testing.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import select

from ..config import ET
from ..db import session_scope
from ..models import AuditLog, Game, audit, utcnow
from .ingest import today_et
from .orchestrator import run_analysis, run_grading

log = logging.getLogger(__name__)
_morning_lock = threading.Lock()
PREGAME_WINDOWS = (60, 15)  # minutes before tip
TOLERANCE_MIN = 5


def due_pregame_windows(games: list[Game], now: dt.datetime, done: set[str]) -> list[tuple[str, int]]:
    """Return (game_id, window) pairs whose pre-game check is due and not done yet."""
    due = []
    for g in games:
        if g.status != "STATUS_SCHEDULED":
            continue
        mins = (g.start_time - now).total_seconds() / 60
        for w in PREGAME_WINDOWS:
            key = f"{g.id}:{w}"
            if key not in done and w - TOLERANCE_MIN <= mins <= w + TOLERANCE_MIN:
                due.append((g.id, w))
    return due


def pregame_tick() -> None:
    now = utcnow()
    with session_scope() as s:
        games = s.execute(select(Game).where(Game.game_date == today_et())).scalars().all()
        done = {r.detail.get("key") for r in s.execute(
            select(AuditLog).where(AuditLog.action == "pregame_check",
                                   AuditLog.at >= now - dt.timedelta(hours=18))).scalars()}
        due = due_pregame_windows(games, now, done)
        for gid, w in due:
            audit(s, "scheduler", "pregame_check", key=f"{gid}:{w}")
    if due:
        ids = sorted({gid for gid, _ in due})
        log.info("pre-game run for %s", due)
        run_analysis(run_type=f"pregame_{min(w for _, w in due)}", odds_game_ids=ids)


def morning_job() -> None:
    from .digest import send_digest
    if not _morning_lock.acquire(blocking=False):
        return  # the scheduled job and the catch-up can both fire on wake
    try:
        run_analysis(run_type="morning")
        with session_scope() as s:
            send_digest(s, today_et(), "morning")
    finally:
        _morning_lock.release()


def morning_catchup_due(now_et: dt.datetime, first_tip: dt.datetime | None, now: dt.datetime,
                        lead_min: int, already_sent: bool) -> bool:
    """Missed morning run: catch up unless the pre-tip run is about to cover it or games have begun."""
    if already_sent or (now_et.hour, now_et.minute) < (9, 10):
        return False
    if first_tip is None:  # schedule not loaded yet, because the morning run is what loads it
        return now_et.hour < 18
    return (first_tip - now).total_seconds() / 60 > lead_min


def catchup_tick() -> None:
    """Also keeps the scheduler's wait short: its timer pauses while the Mac sleeps, so a long
    wait would otherwise leave it silent for hours after waking."""
    from ..config import get_settings
    from ..models import Notification
    from .digest import first_tip
    day, now = today_et(), utcnow()
    with session_scope() as s:
        tip = first_tip(s, day)
        sent = s.execute(select(Notification.id).where(Notification.dedupe_key == f"digest-morning-{day}")).first()
    if morning_catchup_due(dt.datetime.now(ET), tip, now, get_settings().pretip_digest_minutes, sent is not None):
        log.info("catching up on the missed morning run for %s", day)
        morning_job()


def pretip_due(first_tip: dt.datetime | None, now: dt.datetime, lead_min: int, already_sent: bool) -> bool:
    """Due once we are within `lead_min` minutes of the first tip (and the game hasn't started)."""
    if first_tip is None or already_sent:
        return False
    mins = (first_tip - now).total_seconds() / 60
    return 0 < mins <= lead_min


def pretip_tick() -> None:
    from ..config import get_settings
    from ..models import Notification
    from .digest import first_tip, send_digest
    day, now = today_et(), utcnow()
    with session_scope() as s:
        tip = first_tip(s, day)
        sent = s.execute(select(Notification.id).where(Notification.dedupe_key == f"digest-pretip-{day}")).first()
        due = pretip_due(tip, now, get_settings().pretip_digest_minutes, sent is not None)
    if not due:
        return
    run_analysis(run_type="pretip")  # fresh injuries + odds right before sending
    with session_scope() as s:
        send_digest(s, day, "pretip")


def weekly_eval() -> None:
    from .learning import train_and_register
    with session_scope() as s:
        mv = train_and_register(s, promote=False)
        audit(s, "scheduler", "weekly_eval", model_version_id=mv.id, gate=mv.metrics.get("gate"))


def build_scheduler(sched_cls=BlockingScheduler):
    from ..config import get_settings
    runs = {r.strip() for r in get_settings().odds_fetch_runs.split(",") if r.strip()}
    sch = sched_cls(timezone=ET)
    sch.add_job(morning_job, "cron", hour=9, minute=0, id="morning",
                misfire_grace_time=3600, coalesce=True)
    # Afternoon / per-game re-runs only make sense with fresh odds (ODDS_FETCH_RUNS); otherwise
    # they would re-check morning picks against old prices and withdraw them as stale.
    if "afternoon" in runs:
        sch.add_job(lambda: run_analysis(run_type="afternoon"), "cron", hour=13, minute=0, id="afternoon",
                    misfire_grace_time=3600, coalesce=True)
    if "pregame" in runs:
        sch.add_job(pregame_tick, "cron", minute="*/5", hour="11-23", id="pregame", coalesce=True, max_instances=1)
    sch.add_job(pretip_tick, "cron", minute="*/5", hour="10-23", id="pretip_digest", coalesce=True, max_instances=1)
    sch.add_job(run_grading, "cron", hour="22,23,0,1,2", minute="*/30", id="grading_night", coalesce=True)
    sch.add_job(run_grading, "cron", hour=9, minute=30, id="grading_morning", coalesce=True,
                misfire_grace_time=6 * 3600)
    sch.add_job(catchup_tick, "interval", minutes=5, id="catchup", coalesce=True, max_instances=1)
    sch.add_job(weekly_eval, "cron", day_of_week="mon", hour=5, id="weekly_eval", coalesce=True)
    return sch


def run_forever() -> None:
    log.info("Courtside scheduler starting (America/New_York)")
    build_scheduler().start()
