"""Database schema.

Design rules enforced here:
* Raw data tables record provenance (`source`, `fetched_at`).
* `odds_snapshots`, `injury_reports`, `predictions`, `prediction_events` and
  `audit_log` are append-only. Predictions are never rewritten: the analytic
  columns are frozen at insert (see `_guard_prediction_updates`); only
  lifecycle/settlement columns may change, and every lifecycle change is
  recorded in `prediction_events`.
* `record_type` keeps backtest, paper, published and real-money records apart.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # ESPN team id
    abbr: Mapped[str] = mapped_column(String(8), index=True)
    name: Mapped[str] = mapped_column(String(64))


class Player(Base):
    __tablename__ = "players"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # ESPN athlete id
    name: Mapped[str] = mapped_column(String(96))
    norm_name: Mapped[str] = mapped_column(String(96), index=True)
    position: Mapped[str | None] = mapped_column(String(8))
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id"))


class Game(Base):
    __tablename__ = "games"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # ESPN event id
    game_date: Mapped[dt.date] = mapped_column(Date, index=True)  # America/New_York date
    start_time: Mapped[dt.datetime] = mapped_column(DateTime)  # UTC, naive
    season: Mapped[int] = mapped_column(Integer, index=True)  # ending year, e.g. 2027
    season_type: Mapped[int] = mapped_column(Integer, default=2)  # 1 pre, 2 reg, 3 post
    home_team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    away_team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    status: Mapped[str] = mapped_column(String(32))  # STATUS_SCHEDULED / STATUS_FINAL ...
    home_score: Mapped[int | None] = mapped_column(Integer)
    away_score: Mapped[int | None] = mapped_column(Integer)
    box_loaded: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(32), default="espn")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    home_team: Mapped[Team] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped[Team] = relationship(foreign_keys=[away_team_id])

    @property
    def is_final(self) -> bool:
        return self.status == "STATUS_FINAL"


class PlayerGameStat(Base):
    __tablename__ = "player_game_stats"
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id"), primary_key=True)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id"), primary_key=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), index=True)
    opponent_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), index=True)
    game_date: Mapped[dt.date] = mapped_column(Date, index=True)
    is_home: Mapped[bool] = mapped_column(Boolean)
    starter: Mapped[bool] = mapped_column(Boolean, default=False)
    dnp: Mapped[bool] = mapped_column(Boolean, default=False)
    minutes: Mapped[float] = mapped_column(Float, default=0.0)
    pts: Mapped[int] = mapped_column(Integer, default=0)
    reb: Mapped[int] = mapped_column(Integer, default=0)
    ast: Mapped[int] = mapped_column(Integer, default=0)
    fg3m: Mapped[int] = mapped_column(Integer, default=0)
    fg3a: Mapped[int] = mapped_column(Integer, default=0)
    fgm: Mapped[int] = mapped_column(Integer, default=0)
    fga: Mapped[int] = mapped_column(Integer, default=0)
    ftm: Mapped[int] = mapped_column(Integer, default=0)
    fta: Mapped[int] = mapped_column(Integer, default=0)
    stl: Mapped[int] = mapped_column(Integer, default=0)
    blk: Mapped[int] = mapped_column(Integer, default=0)
    tov: Mapped[int] = mapped_column(Integer, default=0)
    oreb: Mapped[int] = mapped_column(Integer, default=0)
    dreb: Mapped[int] = mapped_column(Integer, default=0)
    pf: Mapped[int] = mapped_column(Integer, default=0)
    plus_minus: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32), default="espn")
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class InjuryReport(Base):
    """Append-only snapshots of the injury report as seen at `fetched_at`."""

    __tablename__ = "injury_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[str] = mapped_column(String(16), index=True)
    player_name: Mapped[str] = mapped_column(String(96))
    team_id: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32))  # Out / Doubtful / Questionable / Day-To-Day / Probable
    detail: Mapped[str | None] = mapped_column(Text)
    reported_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(String(32), default="espn")
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)


class OddsSnapshot(Base):
    """Append-only. One row = one book's two-way price for one player prop at one time."""

    __tablename__ = "odds_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id"), index=True)
    player_id: Mapped[str | None] = mapped_column(ForeignKey("players.id"), index=True)
    player_name_raw: Mapped[str] = mapped_column(String(96))
    market: Mapped[str] = mapped_column(String(32))  # internal market key, e.g. "pts"
    book: Mapped[str] = mapped_column(String(32))
    line: Mapped[float] = mapped_column(Float)
    over_price: Mapped[int | None] = mapped_column(Integer)  # American odds
    under_price: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32))  # "the-odds-api" | "manual"
    book_last_update: Mapped[dt.datetime | None] = mapped_column(DateTime)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="candidate")  # candidate|production|retired
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    trained_through: Mapped[dt.date | None] = mapped_column(Date)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    promoted_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("name", "version"),)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_type: Mapped[str] = mapped_column(String(32))  # morning|afternoon|pregame|manual|grading|backtest
    target_date: Mapped[dt.date | None] = mapped_column(Date)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|ok|error
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class Projection(Base):
    """Append-only per-run player projections (independent of whether odds exist)."""

    __tablename__ = "projections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id"), index=True)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id"), index=True)
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    proj_minutes: Mapped[float] = mapped_column(Float)
    sd_minutes: Mapped[float] = mapped_column(Float)
    injury_status: Mapped[str | None] = mapped_column(String(32))
    n_games: Mapped[int] = mapped_column(Integer)
    markets: Mapped[dict[str, Any]] = mapped_column(JSON)  # market -> {mean,p10,p50,p90}
    features: Mapped[dict[str, Any]] = mapped_column(JSON)


FROZEN_PREDICTION_COLUMNS = {
    "run_id", "game_id", "player_id", "market", "side", "line", "book", "price",
    "odds_snapshot_id", "odds_fetched_at", "model_version_id", "created_at",
    "proj_mean", "proj_p10", "proj_p50", "proj_p90", "proj_minutes", "model_prob",
    "implied_prob", "novig_prob", "consensus_prob", "fair_odds", "ev", "kelly_stake",
    "eligible", "reasons", "factors", "risks", "record_type", "published", "data_quality",
}


class Prediction(Base):
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id"), index=True)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id"), index=True)
    market: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(8))  # over|under
    line: Mapped[float] = mapped_column(Float)
    book: Mapped[str] = mapped_column(String(32))
    price: Mapped[int] = mapped_column(Integer)
    odds_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("odds_snapshots.id"))
    odds_fetched_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)

    proj_mean: Mapped[float] = mapped_column(Float)
    proj_p10: Mapped[float] = mapped_column(Float)
    proj_p50: Mapped[float] = mapped_column(Float)
    proj_p90: Mapped[float] = mapped_column(Float)
    proj_minutes: Mapped[float] = mapped_column(Float)
    model_prob: Mapped[float] = mapped_column(Float)
    implied_prob: Mapped[float] = mapped_column(Float)
    novig_prob: Mapped[float | None] = mapped_column(Float)
    consensus_prob: Mapped[float | None] = mapped_column(Float)
    fair_odds: Mapped[int] = mapped_column(Integer)
    ev: Mapped[float] = mapped_column(Float)
    kelly_stake: Mapped[float] = mapped_column(Float, default=0.0)
    eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list)  # why ineligible
    factors: Mapped[list[str]] = mapped_column(JSON, default=list)  # supporting factors
    risks: Mapped[list[str]] = mapped_column(JSON, default=list)
    data_quality: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    record_type: Mapped[str] = mapped_column(String(16), default="paper")  # backtest|paper|published
    published: Mapped[bool] = mapped_column(Boolean, default=False)

    # lifecycle + settlement (mutable, every change also logged as a PredictionEvent)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|superseded|withdrawn|locked
    result: Mapped[str | None] = mapped_column(String(16))  # win|loss|push|void|unresolved
    actual: Mapped[float | None] = mapped_column(Float)
    actual_minutes: Mapped[float | None] = mapped_column(Float)
    error_tags: Mapped[list[str] | None] = mapped_column(JSON)
    settled_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    closing_price: Mapped[int | None] = mapped_column(Integer)
    closing_line: Mapped[float | None] = mapped_column(Float)

    game: Mapped[Game] = relationship()
    player: Mapped[Player] = relationship()


@event.listens_for(Prediction, "before_update")
def _guard_prediction_updates(mapper, connection, target):  # pragma: no cover - exercised in tests
    state = inspect(target)
    changed = {a.key for a in state.attrs if a.history.has_changes()}
    illegal = changed & FROZEN_PREDICTION_COLUMNS
    if illegal:
        raise ValueError(f"Predictions are immutable; refused update of {sorted(illegal)}")


class PredictionEvent(Base):
    __tablename__ = "prediction_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"), index=True)
    event: Mapped[str] = mapped_column(String(32))  # created|published|superseded|withdrawn|settled|locked
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ManualBet(Base):
    """A real-money wager the user confirms they placed. Kept apart from model records."""

    __tablename__ = "manual_bets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prediction_id: Mapped[int | None] = mapped_column(ForeignKey("predictions.id"))
    description: Mapped[str] = mapped_column(String(256))
    book: Mapped[str] = mapped_column(String(32))
    price: Mapped[int] = mapped_column(Integer)
    stake_units: Mapped[float] = mapped_column(Float)
    placed_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    result: Mapped[str | None] = mapped_column(String(16))
    profit_units: Mapped[float | None] = mapped_column(Float)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(32))  # scheduler|api|cli|orchestrator
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dedupe_key: Mapped[str] = mapped_column(String(128), unique=True)
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)
    delivered: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class UserPreferences(Base):
    __tablename__ = "user_preferences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


def audit(session, actor: str, action: str, **detail: Any) -> None:
    session.add(AuditLog(actor=actor, action=action, detail=_jsonable(detail)))


def _jsonable(d: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in d.items():
        if isinstance(v, (dt.date, dt.datetime)):
            v = v.isoformat()
        out[k] = v
    return out
