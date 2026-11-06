"use client";
import clsx from "clsx";
import { AlertTriangle, Check, Minus } from "lucide-react";
import type { ReactNode } from "react";
import { Skeleton, StatusDot } from "@/components/ui";
import { ago, fmtTime, num } from "@/lib/api";
import { engineStatus, oddsFeedLabel } from "@/lib/status";
import type { Block, Health, ModelInfo, Run } from "@/lib/types";

const LABEL = { operational: "Operational", degraded: "Degraded", offline: "Offline" };

function Cell({ label, children, sub }: { label: string; children: ReactNode; sub?: ReactNode }) {
  return (
    <div className="min-w-0 px-4 py-3">
      <div className="text-xs text-ink-2">{label}</div>
      <div className="mt-1 text-sm break-words text-ink">{children}</div>
      {sub && <div className="mt-0.5 text-xs leading-snug text-ink-2">{sub}</div>}
    </div>
  );
}

type StepState = "ok" | "warn" | "none";
function stepState(v: unknown): StepState {
  if (v == null) return "none";
  if (typeof v === "string") return v.startsWith("error") ? "warn" : v.startsWith("skipped") ? "none" : "ok";
  return "ok";
}

/** The real steps of the last analysis run. No progress percentage is shown because none exists. */
function Pipeline({ run }: { run: Run | undefined }) {
  const steps = run?.summary?.steps ?? {};
  const items: [string, StepState][] = [
    ["Schedule", stepState(steps.schedule)],
    ["Box scores", stepState(steps.box_scores)],
    ["Injuries", stepState(steps.injuries)],
    ["Odds", stepState(steps.odds)],
    ["Analysis", run?.status === "ok" && run.summary?.analysis ? "ok" : run?.status === "error" ? "warn" : "none"],
  ];
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line px-4 py-2 text-xs text-ink-2">
      <span>{run ? <>Last run #{run.id} ({run.type})</> : "No analysis has run"}</span>
      {items.map(([name, s]) => (
        <span key={name} className="inline-flex items-center gap-1">
          {s === "ok" && <Check size={12} className="text-good" aria-label="done" />}
          {s === "warn" && <AlertTriangle size={12} className="text-warning" aria-label="problem" />}
          {s === "none" && <Minus size={12} aria-label="skipped" />}
          {name}
        </span>
      ))}
    </div>
  );
}

export function EnginePanel({ health, healthError, runs, models, live, gamesOnSlate, isToday }: {
  health: Health | null; healthError: string | null; runs: Run[] | null; models: ModelInfo[] | null;
  live: Block | null; gamesOnSlate: number | null; isToday: boolean;
}) {
  const { state, reasons } = engineStatus(health, healthError, gamesOnSlate, isToday);
  const lastRun = runs?.find((r) => r.type !== "grading");
  const lastGood = runs?.find((r) => r.type !== "grading" && r.status === "ok");
  const prod = models?.find((m) => m.status === "production");
  const pts = prod?.metrics.markets?.pts;
  const feed = health ? oddsFeedLabel(health) : null;

  return (
    <section className="overflow-hidden rounded-xl border border-line bg-surface" aria-label="Courtside Intelligence Engine">
      <div className={clsx("flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-4 py-2.5")}>
        <h2 className="eyebrow">Courtside Intelligence Engine</h2>
        <span className="inline-flex items-center gap-1.5 text-sm text-ink"><StatusDot state={state} /> {LABEL[state]}</span>
        {reasons.length > 0 && <span className="text-xs text-ink-2">{reasons.join(" ")}</span>}
      </div>
      {!health && !healthError ? <div className="p-4"><Skeleton className="h-14 w-full" /></div> : (
        <div className="grid grid-cols-2 divide-line md:grid-cols-3 xl:grid-cols-5 [&>*]:border-b [&>*]:border-line xl:[&>*]:border-b-0 xl:[&>*:not(:last-child)]:border-r">
          <Cell label="Model" sub={health?.production_model ? `Trained through ${health.production_model.trained_through}` : "Nothing can be published"}>
            {health?.production_model ? <span className="num">{health.production_model.name} v{health.production_model.version}</span> : "No approved model"}
          </Cell>
          <Cell label="Last successful analysis" sub={lastGood ? fmtTime(lastGood.finished_at ?? lastGood.started_at) : undefined}>
            {lastGood ? ago(lastGood.finished_at ?? lastGood.started_at) : "None yet"}
          </Cell>
          <Cell label="Historical forecast skill"
                sub={pts ? `Backtest on proxy lines, n=${pts.n.toLocaleString("en-US")}. Measures forecasts, not profit. Live: ${live?.n ? `${live.wins}-${live.losses}-${live.pushes}, n=${live.n}` : "no graded picks yet"}.` : undefined}>
            {pts ? <span className="num">PTS Brier {num(pts.brier_model, 3)} vs {num(pts.brier_naive, 3)} naive</span> : "Not available"}
          </Cell>
          <Cell label="Odds feed" sub={health?.odds_credits_remaining != null ? `${health.odds_credits_remaining} credits left at last pull` : health?.odds_feed_configured ? "Balance known after the next pull" : undefined}>
            <span className={clsx(feed && !feed.fresh && "text-warning")}>{feed?.text ?? "—"}</span>
          </Cell>
          <Cell label="Injury feed" sub={health?.latest_injury_fetched_at ? fmtTime(health.latest_injury_fetched_at) : undefined}>
            {health ? <span className={clsx(!health.injury_report_fresh && "text-warning")}>{health.injury_report_fresh ? "Fetched" : "Stale: fetched"} {ago(health.latest_injury_fetched_at)}</span> : "—"}
          </Cell>
        </div>
      )}
      <Pipeline run={lastRun} />
    </section>
  );
}
