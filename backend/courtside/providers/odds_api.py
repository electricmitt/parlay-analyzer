"""The Odds API (https://the-odds-api.com) — documented, key-based odds feed.

Cost model (as documented by the provider): the event-odds endpoint costs
`markets x regions` credits per event; listing events is free. Supplying
`bookmakers` instead of `regions` costs 1 region per 10 bookmakers. The free tier
is 500 credits/month, so by default we request only `player_points`.

Hard Rock Bet is exposed under the bookmaker key `hardrockbet` (US regions).
We never invent prices: any market the feed does not return is simply absent.
"""
from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import get_settings
from .espn import ProviderError, _parse_iso

MARKET_MAP = {
    "player_points": "pts",
    "player_rebounds": "reb",
    "player_assists": "ast",
    "player_threes": "fg3m",
    "player_points_rebounds_assists": "pra",
    "player_points_rebounds": "pr",
    "player_points_assists": "pa",
    "player_rebounds_assists": "ra",
    "player_steals": "stl",
    "player_blocks": "blk",
    "player_turnovers": "tov",
}


@dataclass
class OddsEvent:
    id: str
    commence_time: dt.datetime
    home_team: str
    away_team: str


@dataclass
class PropQuote:
    event_id: str
    player_name: str
    market: str  # internal key
    book: str
    line: float
    over_price: int | None
    under_price: int | None
    book_last_update: dt.datetime | None


RETRY_STATUS = {429, 500, 502, 503, 504}
RETRY_DELAYS_S = (1.0, 3.0)


class OddsAPIClient:
    def __init__(self, api_key: str | None = None, client: httpx.Client | None = None):
        s = get_settings()
        self.key = api_key or s.odds_api_key
        if not self.key:
            raise ProviderError("ODDS_API_KEY is not configured; use manual odds entry instead")
        self.base = s.odds_api_base_url
        self.client = client or httpx.Client(timeout=s.http_timeout_s)
        self.remaining: str | None = None
        self.used: str | None = None

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        """Retries temporary failures. Errors never include the request URL, which holds the key."""
        failure = ""
        for delay in (*RETRY_DELAYS_S, None):
            try:
                r = self.client.get(f"{self.base}/{path}", params={"apiKey": self.key, **params})
            except httpx.HTTPError as e:
                failure = type(e).__name__
            else:
                self.remaining = r.headers.get("x-requests-remaining", self.remaining)
                self.used = r.headers.get("x-requests-used", self.used)
                if r.status_code == 200:
                    return r.json()
                failure = f"HTTP {r.status_code}: {r.text[:200]}"
                if r.status_code not in RETRY_STATUS:
                    break
            if delay is not None:
                time.sleep(delay)
        raise ProviderError(f"Odds API {path} {failure}")

    def events(self) -> list[OddsEvent]:
        data = self._get("sports/basketball_nba/events", {"dateFormat": "iso"})
        return [OddsEvent(id=e["id"], commence_time=_parse_iso(e["commence_time"]),
                          home_team=e["home_team"], away_team=e["away_team"]) for e in data]

    def event_props(self, event_id: str, markets: list[str] | None = None,
                    bookmakers: list[str] | None = None) -> list[PropQuote]:
        s = get_settings()
        markets = markets or [m.strip() for m in s.odds_api_markets.split(",") if m.strip()]
        bookmakers = bookmakers or [b.strip() for b in s.odds_api_bookmakers.split(",") if b.strip()]
        data = self._get(
            f"sports/basketball_nba/events/{event_id}/odds",
            {"markets": ",".join(markets), "bookmakers": ",".join(bookmakers),
             "oddsFormat": "american", "dateFormat": "iso"},
        )
        return parse_event_props(data)


def parse_event_props(data: dict[str, Any]) -> list[PropQuote]:
    """Pair Over/Under outcomes per (book, market, player, line)."""
    quotes: dict[tuple, PropQuote] = {}
    for bm in data.get("bookmakers", []):
        for mk in bm.get("markets", []):
            internal = MARKET_MAP.get(mk["key"])
            if internal is None:
                continue
            upd = _parse_iso(mk.get("last_update") or bm.get("last_update"))
            for o in mk.get("outcomes", []):
                player = o.get("description")
                point = o.get("point")
                side = (o.get("name") or "").lower()
                if player is None or point is None or side not in ("over", "under"):
                    continue
                key = (bm["key"], internal, player, float(point))
                q = quotes.setdefault(key, PropQuote(
                    event_id=data["id"], player_name=player, market=internal, book=bm["key"],
                    line=float(point), over_price=None, under_price=None, book_last_update=upd))
                if side == "over":
                    q.over_price = int(o["price"])
                else:
                    q.under_price = int(o["price"])
    return list(quotes.values())
