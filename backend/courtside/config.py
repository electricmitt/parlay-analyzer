"""Runtime configuration. Every value can be overridden by an environment variable
(prefix COURTSIDE_ is NOT used; names match .env.example exactly)."""
from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

ET = ZoneInfo("America/New_York")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./courtside.db"

    # --- Data providers -------------------------------------------------
    espn_base_url: str = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
    espn_min_interval_s: float = 0.6  # polite rate limit between ESPN requests
    http_timeout_s: float = 20.0

    odds_api_key: str | None = None
    odds_api_base_url: str = "https://api.the-odds-api.com/v4"
    # Each market x region costs credits per event. Keep this small on the free tier.
    odds_api_markets: str = "player_points"
    odds_api_bookmakers: str = "hardrockbet,draftkings,fanduel,betmgm,williamhill_us"
    preferred_book: str = "hardrockbet"
    # Which scheduled runs pull fresh odds (morning, afternoon, pregame, pretip). Runs not
    # listed are not scheduled at all: re-analysing on old odds would only mark picks stale.
    odds_fetch_runs: str = "morning,afternoon,pregame,pretip"
    # Stop pulling odds when the monthly balance would drop below this many credits.
    odds_api_min_credits: int = 0

    # --- Eligibility filters (initial defaults; tune via walk-forward only) ---
    min_ev: float = 0.03                 # minimum EV per unit staked
    max_odds_age_min: int = 45           # odds older than this are stale
    min_games_history: int = 8           # player games with minutes in the lookback window
    max_model_market_gap: float = 0.15   # |model prob - no-vig market prob| guard
    max_minutes_cv: float = 0.35         # uncertainty guard on minutes projection
    min_prob: float = 0.30               # skip long-shot sides for single props
    max_prob: float = 0.85
    # Weight on the model when blending with the no-vig market, in log-odds. 1.0 = model only.
    # Below 1.0 is a provisional safeguard: the weight is an assumption until real-line results exist.
    market_blend_weight: float = 1.0

    # --- Staking analysis (informational only; the system never places bets) ---
    bankroll_units: float = 100.0
    kelly_fraction: float = 0.25
    max_stake_pct: float = 0.01

    # --- Modelling -------------------------------------------------------
    n_sims: int = 20000
    random_seed: int = 7

    # --- Scheduler ---------------------------------------------------------
    enable_scheduler: bool = False

    # --- Notifications (optional) ---------------------------------------
    discord_webhook_url: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    # which notification kinds each push channel receives ("all" = everything)
    telegram_kinds: str = "digest,withdrawal,ops"
    discord_kinds: str = "digest,withdrawal,ops"
    pretip_digest_minutes: int = 30  # send the pre-tip digest this long before the first game

    cors_origins: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
