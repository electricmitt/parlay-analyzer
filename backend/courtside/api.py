"""FastAPI application serving the dashboard."""
from __future__ import annotations

import datetime as dt
import threading
from collections import defaultdict
from typing import Any

import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .config import ET, get_settings
from .db import SessionLocal
from .models import (
    AnalysisRun, AuditLog, Game, InjuryReport, ManualBet, ModelVersion, Notification, OddsSnapshot, Player,
    PlayerGameStat, Prediction, PredictionEvent, Projection, Team, UserPreferences, audit, utcnow,
)
from .modeling.baseline import MARKET_LABELS, MARKETS, market_components
from .odds_math import profit_units
from .services import learning
from .services.ingest import add_manual_odds, injuries_fresh, latest_injuries, today_et
from .services.parlay import analyze_parlay
from .services.performance import performance_report, settled_predictions

app = FastAPI(title="Courtside AI", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins.split(","), allow_methods=["*"],
                   allow_headers=["*"])


def db():
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def _iso(d: dt.datetime | None) -> str | None:
    return None if d is None else d.replace(tzinfo=dt.timezone.utc).isoformat()


def _date_or_today(d: str | None) -> dt.date:
    return dt.date.fromisoformat(d) if d else today_et()


def _game_dict(g: Game) -> dict:
    return {"id": g.id, "date": str(g.game_date), "start_time": _iso(g.start_time), "status": g.status,
            "home": {"id": g.home_team_id, "abbr": g.home_team.abbr, "name": g.home_team.name, "score": g.home_score},
            "away": {"id": g.away_team_id, "abbr": g.away_team.abbr, "name": g.away_team.name, "score": g.away_score},
            "started": g.start_time <= utcnow()}


def _pred_dict(p: Prediction, player: Player | None = None, game: Game | None = None) -> dict:
    player = player or p.player
    d = {"id": p.id, "game_id": p.game_id, "player_id": p.player_id, "player": player.name if player else None,
         "market": p.market, "market_label": MARKET_LABELS.get(p.market, p.market), "side": p.side,
         "line": p.line, "book": p.book, "price": p.price, "model_prob": p.model_prob, "implied_prob": p.implied_prob,
         "novig_prob": p.novig_prob, "consensus_prob": p.consensus_prob, "fair_odds": p.fair_odds, "ev": p.ev,
         "kelly_stake_units": p.kelly_stake, "proj_mean": p.proj_mean, "proj_p10": p.proj_p10, "proj_p50": p.proj_p50,
         "proj_p90": p.proj_p90, "proj_minutes": p.proj_minutes, "eligible": p.eligible, "reasons": p.reasons,
         "factors": p.factors, "risks": p.risks, "data_quality": p.data_quality, "record_type": p.record_type,
         "published": p.published, "status": p.status, "result": p.result, "actual": p.actual,
         "actual_minutes": p.actual_minutes, "error_tags": p.error_tags, "created_at": _iso(p.created_at),
         "odds_fetched_at": _iso(p.odds_fetched_at), "model_version_id": p.model_version_id,
         "closing_price": p.closing_price, "closing_line": p.closing_line,
         "risk_level": _risk_level(p)}
    if game is not None:
        d["game"] = f"{game.away_team.abbr} @ {game.home_team.abbr}"
        d["start_time"] = _iso(game.start_time)
        if player and player.team_id == game.home_team_id:
            d["team"], d["opponent"] = game.home_team.abbr, game.away_team.abbr
        elif player and player.team_id == game.away_team_id:
            d["team"], d["opponent"] = game.away_team.abbr, game.home_team.abbr
    return d


def _risk_level(p: Prediction) -> str:
    """Descriptive band from the 80% interval width relative to the line; not a probability."""
    width = (p.proj_p90 - p.proj_p10) / max(p.line, 1)
    return "low" if width < 0.6 else "moderate" if width < 1.0 else "high"


# --------------------------------------------------------------------------- health / slate
@app.get("/api/health")
def health(s: Session = Depends(db)):
    last_runs = s.execute(select(AnalysisRun).order_by(AnalysisRun.started_at.desc()).limit(5)).scalars().all()
    latest_stat = s.execute(select(func.max(PlayerGameStat.game_date))).scalar()
    prod = learning.production_model(s)
    st = get_settings()
    credits = s.execute(select(AuditLog).where(AuditLog.action == "ingest_odds").order_by(AuditLog.at.desc())
                        .limit(1)).scalars().first()
    return {
        "time_et": dt.datetime.now(ET).isoformat(),
        "latest_odds_fetched_at": _iso(s.execute(select(func.max(OddsSnapshot.fetched_at))).scalar()),
        "latest_injury_fetched_at": _iso(s.execute(select(func.max(InjuryReport.fetched_at))).scalar()),
        "odds_credits_remaining": (credits.detail or {}).get("credits_remaining") if credits else None,
        "odds_credits_checked_at": _iso(credits.at) if credits else None,
        "odds_markets": [m.strip() for m in st.odds_api_markets.split(",") if m.strip()],
        "odds_fetch_runs": [r.strip() for r in st.odds_fetch_runs.split(",") if r.strip()],
        "latest_box_score_date": str(latest_stat) if latest_stat else None,
        "player_game_rows": s.execute(select(func.count()).select_from(PlayerGameStat)).scalar(),
        "injury_report_fresh": injuries_fresh(s),
        "odds_feed_configured": bool(st.odds_api_key),
        "production_model": None if prod is None else {"id": prod.id, "name": prod.name, "version": prod.version,
                                                        "trained_through": str(prod.trained_through)},
        "recent_runs": [{"id": r.id, "type": r.run_type, "status": r.status, "started_at": _iso(r.started_at),
                         "finished_at": _iso(r.finished_at), "error": (r.error or "")[-300:] or None,
                         "summary": r.summary} for r in last_runs],
    }


def _latest_active(s: Session, game_ids: list[str]) -> list[Prediction]:
    return list(s.execute(select(Prediction).where(Prediction.game_id.in_(game_ids),
                                                   Prediction.status.in_(["active", "locked"]))).scalars())


def _team_records(s: Session, season: int, before: dt.date) -> dict[str, str]:
    """Regular-season W-L from the final scores stored here, so a missed ingest would undercount."""
    wins: dict[str, int] = defaultdict(int)
    losses: dict[str, int] = defaultdict(int)
    finals = s.execute(select(Game.home_team_id, Game.away_team_id, Game.home_score, Game.away_score).where(
        Game.season == season, Game.season_type == 2, Game.status == "STATUS_FINAL", Game.game_date < before,
        Game.home_score.is_not(None), Game.away_score.is_not(None))).all()
    for home, away, hs, aw in finals:
        winner, loser = (home, away) if hs > aw else (away, home)
        wins[winner] += 1
        losses[loser] += 1
    return {t: f"{wins[t]}-{losses[t]}" for t in {*wins, *losses}}


@app.get("/api/slate")
def slate(date: str | None = None, s: Session = Depends(db)):
    day = _date_or_today(date)
    games = s.execute(select(Game).where(Game.game_date == day).order_by(Game.start_time)).scalars().all()
    preds = _latest_active(s, [g.id for g in games])
    by_game = defaultdict(list)
    for p in preds:
        by_game[p.game_id].append(p)
    records = _team_records(s, games[0].season, day) if games else {}
    injuries = defaultdict(list)
    for r in latest_injuries(s).values():
        injuries[r.team_id].append({"player_id": r.player_id, "player": r.player_name, "status": r.status})
    out = []
    for g in games:
        ps = by_game[g.id]
        picks = [p for p in ps if p.published]
        out.append({**_game_dict(g), "props_evaluated": len(ps), "eligible": sum(p.eligible for p in ps),
                    "published": len(picks), "decision": "PICKS" if picks else ("PASS" if ps else "NO ODDS"),
                    "home_record": records.get(g.home_team_id), "away_record": records.get(g.away_team_id),
                    "injuries": {"home": injuries[g.home_team_id], "away": injuries[g.away_team_id]}})
    # Zero stored games only means "none scheduled" once a successful run has checked this date.
    checked = s.execute(select(AnalysisRun.id).where(AnalysisRun.target_date == day, AnalysisRun.status == "ok",
                                                     AnalysisRun.run_type != "grading").limit(1)).first()
    return {"date": str(day), "games": out, "schedule_loaded": bool(games) or checked is not None,
            "totals": {"games": len(games), "props_evaluated": len(preds), "eligible": sum(p.eligible for p in preds),
                       "published": sum(p.published for p in preds)}}


@app.get("/api/recommendations")
def recommendations(date: str | None = None, s: Session = Depends(db)):
    day = _date_or_today(date)
    games = {g.id: g for g in s.execute(select(Game).where(Game.game_date == day)).scalars()}
    preds = [p for p in _latest_active(s, list(games)) if p.published]
    preds.sort(key=lambda p: p.ev, reverse=True)
    withdrawn = s.execute(select(Prediction).where(Prediction.game_id.in_(list(games)),
                                                   Prediction.status == "withdrawn")).scalars().all()
    return {"date": str(day), "picks": [_pred_dict(p, game=games[p.game_id]) for p in preds],
            "withdrawn": [_pred_dict(p, game=games[p.game_id]) for p in withdrawn],
            "disclaimer": "Model estimates, not guarantees. Positive EV means a favourable price under the model; "
                          "individual bets lose often. Recommendations only — no wagers are placed."}


@app.get("/api/props")
def props(date: str | None = None, game_id: str | None = None, eligible_only: bool = False,
          s: Session = Depends(db)):
    day = _date_or_today(date)
    games = {g.id: g for g in s.execute(select(Game).where(Game.game_date == day)).scalars()}
    ids = [game_id] if game_id else list(games)
    preds = _latest_active(s, ids)
    if eligible_only:
        preds = [p for p in preds if p.eligible]
    preds.sort(key=lambda p: p.ev, reverse=True)
    return [_pred_dict(p, game=games.get(p.game_id)) for p in preds]


# --------------------------------------------------------------------------- game analyzer
def _team_form(s: Session, team_id: str, before: dt.date, n: int = 15) -> dict:
    rows = s.execute(
        select(PlayerGameStat.game_id, PlayerGameStat.game_date, PlayerGameStat.team_id,
               func.sum(PlayerGameStat.pts), func.sum(PlayerGameStat.fga), func.sum(PlayerGameStat.oreb),
               func.sum(PlayerGameStat.tov), func.sum(PlayerGameStat.fta), func.sum(PlayerGameStat.reb),
               func.sum(PlayerGameStat.ast), func.sum(PlayerGameStat.fg3m))
        .join(Game, Game.id == PlayerGameStat.game_id)
        .where(or_(Game.home_team_id == team_id, Game.away_team_id == team_id), Game.game_date < before,
               Game.season_type.in_([2, 3]))
        .group_by(PlayerGameStat.game_id, PlayerGameStat.game_date, PlayerGameStat.team_id)
    ).all()
    games: dict[str, dict] = defaultdict(dict)
    for gid, gd, tid, pts, fga, oreb, tov, fta, reb, ast, fg3m in rows:
        poss = fga - oreb + tov + 0.44 * fta
        games[gid]["date"] = gd
        games[gid]["us" if tid == team_id else "them"] = {"pts": pts, "poss": poss, "reb": reb, "ast": ast, "fg3m": fg3m}
    recent = sorted([g for g in games.values() if "us" in g and "them" in g], key=lambda g: g["date"])[-n:]
    if not recent:
        return {"games": 0}
    poss = np.mean([(g["us"]["poss"] + g["them"]["poss"]) / 2 for g in recent])
    off = np.mean([100 * g["us"]["pts"] / g["us"]["poss"] for g in recent])
    de = np.mean([100 * g["them"]["pts"] / g["them"]["poss"] for g in recent])
    return {"games": len(recent), "pace": round(float(poss), 1), "off_rating": round(float(off), 1),
            "def_rating": round(float(de), 1), "pts": round(float(np.mean([g["us"]["pts"] for g in recent])), 1),
            "opp_pts": round(float(np.mean([g["them"]["pts"] for g in recent])), 1)}


@app.get("/api/games/{game_id}")
def game_detail(game_id: str, s: Session = Depends(db)):
    g = s.get(Game, game_id)
    if g is None:
        raise HTTPException(404, "game not found")
    home, away = _team_form(s, g.home_team_id, g.game_date), _team_form(s, g.away_team_id, g.game_date)
    env = None
    if home.get("games") and away.get("games"):
        poss = (home["pace"] + away["pace"]) / 2
        h_pts = poss * (home["off_rating"] + away["def_rating"]) / 200
        a_pts = poss * (away["off_rating"] + home["def_rating"]) / 200
        env = {"projected_possessions": round(poss, 1), "projected_home": round(h_pts, 1),
               "projected_away": round(a_pts, 1), "method": "last-15 pace and ratings average (no home-court term)"}
    run_id = s.execute(select(func.max(Projection.run_id)).where(Projection.game_id == game_id)).scalar()
    projections = []
    if run_id is not None:
        for pr in s.execute(select(Projection).where(Projection.game_id == game_id, Projection.run_id == run_id)
                            .order_by(Projection.proj_minutes.desc())).scalars():
            pl = s.get(Player, pr.player_id)
            projections.append({"player_id": pr.player_id, "player": pl.name, "team_id": pl.team_id,
                                "position": pl.position, "minutes": pr.proj_minutes, "sd_minutes": pr.sd_minutes,
                                "injury_status": pr.injury_status, "n_games": pr.n_games, "markets": pr.markets,
                                "created_at": _iso(pr.created_at)})
    inj = latest_injuries(s)
    injuries = [{"player_id": r.player_id, "player": r.player_name, "team_id": r.team_id, "status": r.status,
                 "detail": r.detail} for r in inj.values() if r.team_id in (g.home_team_id, g.away_team_id)]
    preds = [_pred_dict(p, game=g) for p in _latest_active(s, [game_id])]
    preds.sort(key=lambda p: p["ev"], reverse=True)
    box = []
    if g.box_loaded:
        for st, pl in s.execute(select(PlayerGameStat, Player).join(Player).where(PlayerGameStat.game_id == game_id)
                                .order_by(PlayerGameStat.minutes.desc())):
            box.append({"player": pl.name, "team_id": st.team_id, "minutes": st.minutes, "pts": st.pts,
                        "reb": st.reb, "ast": st.ast, "fg3m": st.fg3m, "dnp": st.dnp})
    return {"game": _game_dict(g), "team_form": {"home": home, "away": away}, "environment": env,
            "projections": projections, "projection_run_id": run_id, "injuries": injuries, "props": preds,
            "box_score": box}


# --------------------------------------------------------------------------- players
@app.get("/api/recent-values")
def recent_values(keys: str = Query(max_length=4000), n: int = Query(10, ge=1, le=30), s: Session = Depends(db)):
    """Last `n` played values per `player_id:market` key, oldest first, for sparklines."""
    out: dict[str, list[float]] = {}
    for key in {k for k in keys.split(",") if ":" in k}:
        player_id, market = key.split(":", 1)
        if market not in MARKETS:
            continue
        rows = s.execute(select(PlayerGameStat).where(PlayerGameStat.player_id == player_id,
                                                      PlayerGameStat.dnp.is_(False), PlayerGameStat.minutes > 0)
                         .order_by(PlayerGameStat.game_date.desc()).limit(n)).scalars().all()
        out[key] = [float(sum(getattr(r, c) for c in market_components(market))) for r in reversed(rows)]
    return out


@app.get("/api/players")
def search_players(q: str = Query(min_length=2), s: Session = Depends(db)):
    rows = s.execute(select(Player).where(Player.norm_name.like(f"%{q.lower()}%")).limit(25)).scalars().all()
    teams = {t.id: t.abbr for t in s.execute(select(Team)).scalars()}
    return [{"id": p.id, "name": p.name, "position": p.position, "team": teams.get(p.team_id)} for p in rows]


@app.get("/api/players/{player_id}")
def player_detail(player_id: str, s: Session = Depends(db)):
    p = s.get(Player, player_id)
    if p is None:
        raise HTTPException(404, "player not found")
    teams = {t.id: t.abbr for t in s.execute(select(Team)).scalars()}
    logs = s.execute(select(PlayerGameStat, Game.season, Game.season_type)
                     .join(Game, Game.id == PlayerGameStat.game_id)
                     .where(PlayerGameStat.player_id == player_id)
                     .order_by(PlayerGameStat.game_date.desc()).limit(82)).all()
    log_rows = [{"date": str(r.game_date), "game_id": r.game_id, "season": season, "season_type": season_type,
                 "opp": teams.get(r.opponent_id), "home": r.is_home, "fta": r.fta,
                 "starter": r.starter, "dnp": r.dnp, "minutes": r.minutes, "pts": r.pts, "reb": r.reb, "ast": r.ast,
                 "fg3m": r.fg3m, "stl": r.stl, "blk": r.blk, "tov": r.tov, "pf": r.pf,
                 "fga": r.fga, "fgm": r.fgm} for r, season, season_type in logs]
    played = [r for r in log_rows if not r["dnp"] and r["minutes"] > 0]

    def avg(rows, k):
        return round(float(np.mean([r[k] for r in rows])), 1) if rows else None
    splits = {}
    for label, rows in (("last_5", played[:5]), ("last_10", played[:10]), ("last_20", played[:20]),
                        ("season", played)):
        splits[label] = {k: avg(rows, k) for k in ("minutes", "pts", "reb", "ast", "fg3m")} | {"games": len(rows)}
    proj = s.execute(select(Projection).where(Projection.player_id == player_id)
                     .order_by(Projection.created_at.desc()).limit(1)).scalars().first()
    hist = s.execute(select(Prediction).where(Prediction.player_id == player_id, Prediction.result.is_not(None),
                                              Prediction.status.in_(["locked", "active"]))
                     .order_by(Prediction.created_at.desc()).limit(50)).scalars().all()
    inj = latest_injuries(s).get(player_id)
    snapshots = s.execute(select(InjuryReport).where(InjuryReport.player_id == player_id)
                          .order_by(InjuryReport.fetched_at)).scalars().all()
    injury_history: list[dict] = []
    for r in snapshots:  # keep only changes, since the same status is re-recorded on every fetch
        if not injury_history or injury_history[-1]["status"] != r.status:
            injury_history.append({"status": r.status, "detail": r.detail, "first_seen": _iso(r.fetched_at)})
    return {"player": {"id": p.id, "name": p.name, "position": p.position, "team": teams.get(p.team_id)},
            "injury_history": injury_history,
            "injury": None if inj is None else {"status": inj.status, "detail": inj.detail},
            "splits": splits, "game_log": log_rows,
            "latest_projection": None if proj is None else {
                "game_id": proj.game_id, "minutes": proj.proj_minutes, "sd_minutes": proj.sd_minutes,
                "markets": proj.markets, "features": proj.features, "created_at": _iso(proj.created_at)},
            "prop_history": [_pred_dict(x) for x in hist]}


@app.get("/api/players/{player_id}/distribution")
def player_distribution(player_id: str, market: str = "pts", s: Session = Depends(db)):
    """Simulated distribution from the player's latest projection (for charting)."""
    from .modeling.baseline import BaselineParams, simulate
    if market not in MARKETS:
        raise HTTPException(400, "unknown market")
    proj = s.execute(select(Projection).where(Projection.player_id == player_id)
                     .order_by(Projection.created_at.desc()).limit(1)).scalars().first()
    if proj is None:
        raise HTTPException(404, "no projection yet")
    mv = s.get(ModelVersion, proj.model_version_id)
    params = BaselineParams.from_dict(mv.params if mv else {})
    row = dict(proj.features)
    draws = simulate(row, params, n=20000, seed=get_settings().random_seed, markets=[market])[market]
    vals, counts = np.unique(draws, return_counts=True)
    return {"market": market, "game_id": proj.game_id,
            "histogram": [{"value": int(v), "p": float(c / len(draws))} for v, c in zip(vals, counts)]}


# --------------------------------------------------------------------------- odds entry / runs
class ManualOdds(BaseModel):
    game_id: str
    player_id: str
    market: str = Field(pattern="^(" + "|".join(MARKETS) + ")$")
    book: str = "hardrockbet"
    line: float
    over_price: int | None = None
    under_price: int | None = None
    reanalyze: bool = True


@app.post("/api/odds/manual")
def manual_odds(body: ManualOdds, s: Session = Depends(db)):
    for price in (body.over_price, body.under_price):
        if price is not None and -100 < price < 100:
            raise HTTPException(400, "American odds must be <= -100 or >= +100")
    try:
        snap = add_manual_odds(s, body.game_id, body.player_id, body.market, body.book, body.line,
                               body.over_price, body.under_price)
    except ValueError as e:
        raise HTTPException(400, str(e))
    s.commit()
    result = None
    if body.reanalyze:
        from .services.orchestrator import run_analysis
        g = s.get(Game, body.game_id)
        result = run_analysis(g.game_date, run_type="manual_odds", fetch_odds=False)
    return {"snapshot_id": snap.id, "analysis": result}


_run_lock = threading.Lock()


@app.post("/api/runs/analyze")
def trigger_analysis(date: str | None = None, fetch_odds: bool = True):
    from .services.orchestrator import run_analysis
    if not _run_lock.acquire(blocking=False):
        raise HTTPException(409, "an analysis run is already in progress")
    try:
        return run_analysis(_date_or_today(date), run_type="manual", fetch_odds=fetch_odds)
    finally:
        _run_lock.release()


@app.post("/api/runs/grade")
def trigger_grading(date: str | None = None):
    from .services.orchestrator import run_grading
    return run_grading(dt.date.fromisoformat(date) if date else None)


@app.get("/api/runs")
def runs(limit: int = 30, s: Session = Depends(db)):
    rs = s.execute(select(AnalysisRun).order_by(AnalysisRun.started_at.desc()).limit(limit)).scalars()
    return [{"id": r.id, "type": r.run_type, "date": str(r.target_date), "status": r.status,
             "started_at": _iso(r.started_at), "finished_at": _iso(r.finished_at), "summary": r.summary,
             "error": r.error} for r in rs]


@app.get("/api/predictions/{pid}/events")
def prediction_events(pid: int, s: Session = Depends(db)):
    ev = s.execute(select(PredictionEvent).where(PredictionEvent.prediction_id == pid)
                   .order_by(PredictionEvent.at)).scalars()
    return [{"event": e.event, "at": _iso(e.at), "detail": e.detail} for e in ev]


# --------------------------------------------------------------------------- performance / models
@app.get("/api/performance")
def performance(record_type: str = Query("published", pattern="^(published|paper|withdrawn|real_money)$"),
                s: Session = Depends(db)):
    rep = performance_report(s, record_type)
    prod = learning.production_model(s)
    rep["backtest"] = None if prod is None else {"model": f"{prod.name} {prod.version}", **prod.metrics}
    return rep


@app.get("/api/predictions/settled")
def settled(record_type: str = Query("published", pattern="^(published|paper|withdrawn)$"),
            limit: int = Query(500, ge=1, le=2000), s: Session = Depends(db)):
    """Projection vs actual for settled props. Record types are never mixed."""
    rows = [p for p in settled_predictions(s, record_type) if p.actual is not None][-limit:]
    return [{"id": p.id, "player": p.player.name, "market": p.market, "market_label": MARKET_LABELS.get(p.market, p.market),
             "side": p.side, "line": p.line, "proj_mean": p.proj_mean, "actual": p.actual, "result": p.result} for p in rows]


class ParlayIn(BaseModel):
    prediction_ids: list[int]
    quoted_price: int | None = None


@app.post("/api/parlay/analyze")
def parlay_analyze(body: ParlayIn, s: Session = Depends(db)):
    """Read-only, experimental estimate. Nothing is stored or published."""
    try:
        return analyze_parlay(s, body.prediction_ids, body.quoted_price)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/results")
def results(date: str | None = None, s: Session = Depends(db)):
    day = _date_or_today(date) if date else today_et() - dt.timedelta(days=1)
    games = {g.id: g for g in s.execute(select(Game).where(Game.game_date == day)).scalars()}
    preds = [p for p in _latest_active(s, list(games)) if p.published and p.result]
    return {"date": str(day), "picks": [_pred_dict(p, game=games[p.game_id]) for p in preds],
            "units": round(sum(profit_units(p.result, p.price) for p in preds), 3)}


@app.get("/api/models")
def models(s: Session = Depends(db)):
    ms = s.execute(select(ModelVersion).order_by(ModelVersion.created_at.desc())).scalars()
    return [{"id": m.id, "name": m.name, "version": m.version, "status": m.status, "metrics": m.metrics,
             "trained_through": str(m.trained_through) if m.trained_through else None,
             "created_at": _iso(m.created_at), "promoted_at": _iso(m.promoted_at), "notes": m.notes,
             "dispersion": (m.params or {}).get("dispersion")} for m in ms]


class PromoteBody(BaseModel):
    confirm_shadow_tested: bool = False
    override_gate: bool = False


@app.post("/api/models/{model_id}/promote")
def promote(model_id: int, body: PromoteBody, s: Session = Depends(db)):
    mv = s.get(ModelVersion, model_id)
    if mv is None:
        raise HTTPException(404)
    gate = (mv.metrics or {}).get("gate", {})
    if not gate.get("pass") and not body.override_gate:
        raise HTTPException(400, f"model did not pass the validation gate: {gate.get('reasons')}")
    if learning.production_model(s) is not None and not body.confirm_shadow_tested:
        raise HTTPException(400, "challengers must be shadow-tested before promotion (confirm_shadow_tested)")
    learning.promote_model(s, mv)
    audit(s, "api", "promote_request", model_version_id=model_id, override_gate=body.override_gate)
    return {"ok": True}


@app.post("/api/models/{model_id}/rollback")
def rollback(model_id: int, s: Session = Depends(db)):
    try:
        learning.rollback(s, model_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


@app.get("/api/learning")
def learning_center(s: Session = Depends(db)):
    settled = list(s.execute(select(Prediction).where(Prediction.result.in_(["win", "loss", "push"]),
                                                      Prediction.status.in_(["locked", "active"]))).scalars())
    by_market = defaultdict(list)
    for p in settled:
        by_market[p.market].append(p)
    return {"errors_overall": learning.error_summary(settled),
            "errors_by_market": {m: learning.error_summary(v) for m, v in by_market.items()},
            "models": models(s)}


# --------------------------------------------------------------------------- misc
@app.get("/api/injuries")
def injuries(s: Session = Depends(db)):
    teams = {t.id: t.abbr for t in s.execute(select(Team)).scalars()}
    rows = latest_injuries(s, max_age_hours=72).values()
    return [{"player_id": r.player_id, "player": r.player_name, "team": teams.get(r.team_id), "status": r.status,
             "detail": r.detail, "reported_at": _iso(r.reported_at), "fetched_at": _iso(r.fetched_at)}
            for r in sorted(rows, key=lambda r: (r.status, r.player_name))]


@app.get("/api/notifications")
def notifications(limit: int = 50, s: Session = Depends(db)):
    ns = s.execute(select(Notification).order_by(Notification.created_at.desc()).limit(limit)).scalars()
    return [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "created_at": _iso(n.created_at),
             "delivered": n.delivered} for n in ns]


DEFAULT_PREFS: dict[str, Any] = {
    "preferred_book": "hardrockbet", "bankroll_units": 100, "preferred_markets": ["pts"], "max_parlay_legs": 3,
    "min_ev": 0.03, "risk_tolerance": "conservative", "alert_channels": ["dashboard"], "teams_filter": [],
}


@app.get("/api/preferences")
def get_prefs(s: Session = Depends(db)):
    p = s.get(UserPreferences, 1)
    return {**DEFAULT_PREFS, **(p.data if p else {})}


@app.put("/api/preferences")
def put_prefs(body: dict[str, Any], s: Session = Depends(db)):
    p = s.get(UserPreferences, 1) or UserPreferences(id=1, data={})
    p.data = {**DEFAULT_PREFS, **(p.data or {}), **{k: v for k, v in body.items() if k in DEFAULT_PREFS}}
    s.add(p)
    audit(s, "api", "preferences_updated", keys=list(body))
    return p.data


class BetIn(BaseModel):
    prediction_id: int | None = None
    description: str
    book: str
    price: int
    stake_units: float = Field(gt=0)


@app.post("/api/bets")
def add_bet(body: BetIn, s: Session = Depends(db)):
    b = ManualBet(**body.model_dump())
    s.add(b)
    s.flush()
    audit(s, "api", "manual_bet_recorded", bet_id=b.id)
    return {"id": b.id}


@app.post("/api/bets/{bet_id}/settle")
def settle_bet(bet_id: int, result: str = Query(pattern="^(win|loss|push|void)$"), s: Session = Depends(db)):
    b = s.get(ManualBet, bet_id)
    if b is None:
        raise HTTPException(404)
    b.result = result
    b.profit_units = profit_units(result, b.price, b.stake_units)
    return {"ok": True, "profit_units": b.profit_units}


@app.get("/api/bets")
def list_bets(s: Session = Depends(db)):
    return [{"id": b.id, "description": b.description, "book": b.book, "price": b.price, "stake_units": b.stake_units,
             "placed_at": _iso(b.placed_at), "result": b.result, "profit_units": b.profit_units}
            for b in s.execute(select(ManualBet).order_by(ManualBet.placed_at.desc())).scalars()]


@app.get("/api/meta")
def meta():
    return {"markets": [{"key": m, "label": MARKET_LABELS[m], "components": market_components(m)} for m in MARKETS],
            "books": ["hardrockbet", "hardrockbet_fl", "draftkings", "fanduel", "betmgm", "williamhill_us", "espnbet", "fanatics", "other"]}
