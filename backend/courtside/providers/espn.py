"""ESPN public site API (no key). Undocumented but publicly served JSON; used for
schedule, box scores and injury reports. All records are tagged source="espn".

We request politely (rate limited, plain client UA, caching of final games) and never
attempt to bypass access controls. If ESPN changes or blocks these endpoints the
ingestion step fails loudly rather than inventing data.
"""
from __future__ import annotations

import datetime as dt
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import get_settings

UA = "CourtsideAI/0.1 (personal research; contact via repo)"


class ProviderError(RuntimeError):
    pass


@dataclass
class TeamRef:
    id: str
    abbr: str
    name: str


@dataclass
class GameRef:
    id: str
    start_time: dt.datetime  # UTC naive
    season: int
    season_type: int
    status: str
    home: TeamRef
    away: TeamRef
    home_score: int | None
    away_score: int | None


@dataclass
class PlayerLine:
    player_id: str
    name: str
    position: str | None
    team_id: str
    starter: bool
    dnp: bool
    dnp_reason: str | None
    stats: dict[str, Any] = field(default_factory=dict)


@dataclass
class InjuryRef:
    player_id: str
    player_name: str
    team_id: str | None
    status: str
    detail: str | None
    reported_at: dt.datetime | None


def _parse_iso(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    if re.match(r".*T\d\d:\d\d\+", s):  # "2026-11-01T20:30+00:00" (no seconds)
        s = s.replace("+00:00", ":00+00:00")
    return dt.datetime.fromisoformat(s).astimezone(dt.timezone.utc).replace(tzinfo=None)


def _int(x: Any) -> int | None:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _made_att(s: str) -> tuple[int, int]:
    m, a = s.split("-")
    return int(m), int(a)


def parse_box_stats(keys: list[str], values: list[str]) -> dict[str, Any]:
    """Map ESPN's positional stat array to our columns. Raises on unexpected shape."""
    row = {k: ("0" if v in ("--", "") else v) for k, v in zip(keys, values)}
    row = {k: ("0-0" if "-" in k and v == "0" else v) for k, v in row.items()}
    out: dict[str, Any] = {}
    out["minutes"] = float(row.get("minutes") or 0)
    out["pts"] = int(row["points"])
    out["reb"] = int(row["rebounds"])
    out["ast"] = int(row["assists"])
    out["tov"] = int(row["turnovers"])
    out["stl"] = int(row["steals"])
    out["blk"] = int(row["blocks"])
    out["oreb"] = int(row["offensiveRebounds"])
    out["dreb"] = int(row["defensiveRebounds"])
    out["pf"] = int(row["fouls"])
    out["fgm"], out["fga"] = _made_att(row["fieldGoalsMade-fieldGoalsAttempted"])
    out["fg3m"], out["fg3a"] = _made_att(row["threePointFieldGoalsMade-threePointFieldGoalsAttempted"])
    out["ftm"], out["fta"] = _made_att(row["freeThrowsMade-freeThrowsAttempted"])
    pm = row.get("plusMinus")
    out["plus_minus"] = _int(pm.replace("+", "")) if isinstance(pm, str) else None
    return out


class ESPNClient:
    def __init__(self, client: httpx.Client | None = None):
        s = get_settings()
        self.base = s.espn_base_url
        self.min_interval = s.espn_min_interval_s
        self.client = client or httpx.Client(timeout=s.http_timeout_s, headers={"User-Agent": UA})
        self._last = 0.0
        self.skipped_rows: list[dict] = []
        self._lock = threading.Lock()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                r = self.client.get(f"{self.base}/{path}", params=params)
                if r.status_code == 200:
                    return r.json()
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(2 ** attempt)
                    last_exc = ProviderError(f"ESPN {path} HTTP {r.status_code}")
                    continue
                raise ProviderError(f"ESPN {path} HTTP {r.status_code}")
            except httpx.HTTPError as e:
                last_exc = e
                time.sleep(2 ** attempt)
        raise ProviderError(f"ESPN {path} failed: {last_exc}")

    # ------------------------------------------------------------------
    def scoreboard(self, day: dt.date) -> list[GameRef]:
        data = self._get("scoreboard", {"dates": day.strftime("%Y%m%d")})
        out = []
        for e in data.get("events", []):
            try:
                out.append(self._parse_event(e))
            except (KeyError, TypeError, ValueError):
                # placeholder (TBD playoff slot) or exhibition with incomplete team data: skip, never guess
                self.skipped_rows.append({"event": e.get("id"), "reason": "unparseable scoreboard event"})
        return out

    @staticmethod
    def _parse_event(e: dict[str, Any]) -> GameRef:
        comp = e["competitions"][0]
        teams: dict[str, TeamRef] = {}
        scores: dict[str, int | None] = {}
        for c in comp["competitors"]:
            t = c["team"]
            teams[c["homeAway"]] = TeamRef(id=str(t["id"]), abbr=t["abbreviation"], name=t["displayName"])
            scores[c["homeAway"]] = _int(c.get("score"))
        status = e["status"]["type"]["name"]
        final = status == "STATUS_FINAL"
        return GameRef(
            id=str(e["id"]),
            start_time=_parse_iso(e["date"]),
            season=int(e["season"]["year"]),
            season_type=int(e["season"]["type"]),
            status=status,
            home=teams["home"],
            away=teams["away"],
            home_score=scores["home"] if final or status == "STATUS_IN_PROGRESS" else None,
            away_score=scores["away"] if final or status == "STATUS_IN_PROGRESS" else None,
        )

    def box_score(self, event_id: str) -> tuple[str, list[PlayerLine]]:
        """Returns (status, player lines). Lines are empty if the game has not started."""
        data = self._get("summary", {"event": event_id})
        status = data["header"]["competitions"][0]["status"]["type"]["name"]
        lines: list[PlayerLine] = []
        for team_block in data.get("boxscore", {}).get("players", []):
            team_id = str(team_block["team"]["id"])
            for stat_group in team_block.get("statistics", []):
                keys = stat_group.get("keys", [])
                for a in stat_group.get("athletes", []):
                    ath = a["athlete"]
                    if not ath.get("id") or not ath.get("displayName"):
                        self.skipped_rows.append({"event": event_id, "stats": a.get("stats")})
                        continue  # cannot identify the player -> never guess
                    dnp = bool(a.get("didNotPlay")) or not a.get("stats")
                    stats = {} if dnp else parse_box_stats(keys, a["stats"])
                    if stats and stats["minutes"] <= 0:
                        dnp = True
                    lines.append(PlayerLine(
                        player_id=str(ath["id"]),
                        name=ath["displayName"],
                        position=(ath.get("position") or {}).get("abbreviation"),
                        team_id=team_id,
                        starter=bool(a.get("starter")),
                        dnp=dnp,
                        dnp_reason=a.get("reason"),
                        stats=stats,
                    ))
        return status, lines

    def injuries(self) -> list[InjuryRef]:
        data = self._get("injuries")
        out: list[InjuryRef] = []
        for team in data.get("injuries", []):
            team_id = str(team.get("id")) if team.get("id") is not None else None
            for inj in team.get("injuries", []):
                ath = inj.get("athlete", {})
                pid = None
                for link in ath.get("links", []):
                    m = re.search(r"/id/(\d+)", link.get("href", ""))
                    if m:
                        pid = m.group(1)
                        break
                if not pid:
                    continue  # cannot identify player reliably -> skip, never guess
                out.append(InjuryRef(
                    player_id=pid,
                    player_name=ath.get("displayName", ""),
                    team_id=team_id,
                    status=inj.get("status", "Unknown"),
                    detail=inj.get("shortComment"),
                    reported_at=_parse_iso(inj.get("date")),
                ))
        return out
