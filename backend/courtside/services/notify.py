"""Notifications: always stored for the dashboard; optionally pushed to Discord/Telegram.

* De-duplicated by `dedupe_key`, so re-runs never repeat an alert.
* Per-channel routing by notification kind (TELEGRAM_KINDS / DISCORD_KINDS), so push
  channels get the daily digests and important changes, not every internal event.
"""
from __future__ import annotations

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Notification

log = logging.getLogger(__name__)
TELEGRAM_LIMIT = 4000  # API hard limit is 4096 characters per message


def notify(s: Session, dedupe_key: str, kind: str, title: str, body: str) -> Notification | None:
    if s.execute(select(Notification.id).where(Notification.dedupe_key == dedupe_key)).first():
        return None
    n = Notification(dedupe_key=dedupe_key, kind=kind, title=title, body=body, delivered={})
    try:
        with s.begin_nested():
            s.add(n)
    except IntegrityError:
        return None
    n.delivered = _deliver(kind, title, body)
    return n


def _wants(kinds_csv: str, kind: str) -> bool:
    kinds = {k.strip() for k in kinds_csv.split(",") if k.strip()}
    return "all" in kinds or kind in kinds


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Split on line boundaries so no message exceeds `limit` characters."""
    chunks, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:  # pathological single line
            chunks.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) + 1 > limit:
            chunks.append(cur.rstrip("\n"))
            cur = ""
        cur += line + "\n"
    if cur.strip():
        chunks.append(cur.rstrip("\n"))
    return chunks


def send_telegram(text: str) -> bool:
    st = get_settings()
    if not (st.telegram_bot_token and st.telegram_chat_id):
        return False
    ok = True
    for chunk in split_message(text):
        try:
            r = httpx.post(f"https://api.telegram.org/bot{st.telegram_bot_token}/sendMessage",
                           json={"chat_id": st.telegram_chat_id, "text": chunk,
                                 "disable_web_page_preview": True}, timeout=15)
            if r.status_code >= 300:
                log.warning("telegram delivery failed: HTTP %s %s", r.status_code, r.text[:200])
                ok = False
        except httpx.HTTPError as e:
            log.warning("telegram delivery failed: %s", e)
            ok = False
    return ok


def _deliver(kind: str, title: str, body: str) -> dict:
    st = get_settings()
    res: dict = {"dashboard": True}
    if st.discord_webhook_url and _wants(st.discord_kinds, kind):
        try:
            r = httpx.post(st.discord_webhook_url, json={"content": f"**{title}**\n{body}"[:1900]}, timeout=10)
            res["discord"] = r.status_code < 300
        except httpx.HTTPError as e:
            log.warning("discord delivery failed: %s", e)
            res["discord"] = False
    if st.telegram_bot_token and st.telegram_chat_id and _wants(st.telegram_kinds, kind):
        res["telegram"] = send_telegram(f"{title}\n\n{body}")
    return res
