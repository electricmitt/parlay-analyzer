"""Command-line entry point: `courtside <command>`."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    p = argparse.ArgumentParser(prog="courtside")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("migrate", help="apply database migrations (alembic upgrade head)")

    b = sub.add_parser("backfill", help="load schedule + box scores for a date range (ET dates)")
    b.add_argument("--start", type=_date, required=True)
    b.add_argument("--end", type=_date, default=None)

    sh = sub.add_parser("shadow-report", help="read-only: production vs paper candidate on real pre-tip lines")
    sh.add_argument("--start", type=_date, required=True)
    sh.add_argument("--end", type=_date, default=None)

    t = sub.add_parser("train", help="walk-forward evaluate + register a baseline model version")
    t.add_argument("--eval-start", type=_date, default=None, help="first date of the out-of-sample window")
    t.add_argument("--promote", action="store_true", help="promote if it passes the champion gate")

    bt = sub.add_parser("backtest", help="walk-forward evaluate a model variant on a fixed window (registers nothing)")
    bt.add_argument("--calib-start", type=_date, required=True, help="start of predictions used as calibrator burn-in")
    bt.add_argument("--eval-start", type=_date, required=True)
    bt.add_argument("--eval-end", type=_date, required=True)
    bt.add_argument("--no-playoff-factor", action="store_true")
    bt.add_argument("--no-calibration", action="store_true")
    bt.add_argument("--out", default=None, help="write full metrics JSON here")

    a = sub.add_parser("analyze", help="run the daily analysis pipeline now")
    a.add_argument("--date", type=_date, default=None)
    a.add_argument("--run-type", default="manual")
    a.add_argument("--no-odds", action="store_true", help="skip The Odds API fetch (use stored/manual odds)")

    g = sub.add_parser("grade", help="refresh results and settle predictions")
    g.add_argument("--date", type=_date, default=None)

    dg = sub.add_parser("digest", help="build (and optionally send) today's digest")
    dg.add_argument("--kind", choices=["morning", "pretip"], default="morning")
    dg.add_argument("--date", type=_date, default=None)
    dg.add_argument("--send", action="store_true", help="push to Telegram/Discord (once per day per kind)")
    dg.add_argument("--force", action="store_true", help="send even if already sent today")

    sub.add_parser("telegram-setup", help="find your chat id after messaging your bot, and send a test")

    sub.add_parser("worker", help="run the scheduler (daily autonomous workflow)")
    sv = sub.add_parser("serve", help="run the API server")
    sv.add_argument("--port", type=int, default=8000)

    args = p.parse_args(argv)

    if args.cmd == "migrate":
        from alembic import command
        from alembic.config import Config
        command.upgrade(Config("alembic.ini"), "head")
        return 0

    if args.cmd == "serve":
        import uvicorn
        uvicorn.run("courtside.api:app", host="0.0.0.0", port=args.port)
        return 0

    if args.cmd == "worker":
        from .services.scheduler import run_forever
        run_forever()
        return 0

    from .db import session_scope

    if args.cmd == "backfill":
        from .services.ingest import backfill, today_et
        end = args.end or (today_et() - dt.timedelta(days=1))
        with session_scope() as s:
            res = backfill(s, args.start, end,
                           progress=lambda d, t: print(f"{d} {t}", flush=True) if d.day in (1, 15) else None)
        print(json.dumps(res))
        return 0

    if args.cmd == "train":
        from .services.learning import train_and_register
        with session_scope() as s:
            mv = train_and_register(s, eval_start=args.eval_start, promote=args.promote)
            print(json.dumps({"model_version_id": mv.id, "status": mv.status, "metrics": mv.metrics},
                             indent=2, default=str))
        return 0

    if args.cmd == "telegram-setup":
        import httpx
        from .config import get_settings
        from .services.notify import send_telegram
        st = get_settings()
        if not st.telegram_bot_token:
            print("Set TELEGRAM_BOT_TOKEN in backend/.env first (create a bot with @BotFather).")
            return 1
        r = httpx.get(f"https://api.telegram.org/bot{st.telegram_bot_token}/getUpdates", timeout=15).json()
        chats = {u["message"]["chat"]["id"]: u["message"]["chat"].get("username") or u["message"]["chat"].get("title")
                 for u in r.get("result", []) if "message" in u}
        if not chats:
            print("No messages found. Open Telegram, send any message to your bot, then re-run this command.")
        for cid, name in chats.items():
            print(f"chat id {cid}  ({name})  -> set TELEGRAM_CHAT_ID={cid} in backend/.env")
        if st.telegram_chat_id:
            ok = send_telegram("Courtside AI: Telegram is connected. Daily digests will arrive here.")
            print("test message sent" if ok else "test message FAILED — check token / chat id")
        return 0

    if args.cmd == "digest":
        from .services.digest import build_digest, send_digest
        from .services.ingest import today_et
        day = args.date or today_et()
        with session_scope() as s:
            if args.send:
                print(json.dumps(send_digest(s, day, args.kind, force=args.force), indent=2, default=str))
            else:
                title, body = build_digest(s, day, args.kind)
                print(title + "\n\n" + body)
        return 0

    if args.cmd == "backtest":
        from .modeling.baseline import BaselineParams
        from .modeling.data import load_history
        from .services.learning import evaluate_window, gate_first_model
        with session_scope() as s:
            hist = load_history(s, before=args.eval_end + dt.timedelta(days=1))
        base = BaselineParams(use_playoff_factor=not args.no_playoff_factor)
        _, metrics = evaluate_window(hist, args.calib_start, args.eval_start, args.eval_end, base,
                                     calibrate=not args.no_calibration)
        metrics["gate"] = gate_first_model(metrics)
        if args.out:
            with open(args.out, "w") as f:
                json.dump(metrics, f, default=str)
        for m, r in metrics.get("markets", {}).items():
            print(f"{m:5s} n={r['n']} brier={r['brier_model']:.4f} naive={r['brier_naive']:.4f} "
                  f"ci=[{r['brier_diff_ci95'][0]:.4f},{r['brier_diff_ci95'][1]:.4f}] ece={r['ece_model']:.3f} "
                  f"cov80={r['coverage_80']:.3f}")
        print(json.dumps(metrics["gate"]))
        return 0

    if args.cmd == "analyze":
        from .services.orchestrator import run_analysis
        summary = run_analysis(args.date, run_type=args.run_type, fetch_odds=not args.no_odds)
        print(json.dumps(summary, indent=2, default=str))
        return 0

    if args.cmd == "shadow-report":
        from .db import session_scope
        from .services.shadow import shadow_report
        with session_scope() as s:
            print(json.dumps(shadow_report(s, args.start, args.end or args.start), indent=2, default=str))
        return 0

    if args.cmd == "grade":
        from .services.orchestrator import run_grading
        print(json.dumps(run_grading(args.date), indent=2, default=str))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
