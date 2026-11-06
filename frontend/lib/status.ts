import { ago, minutesSince } from "./api";
import type { Health } from "./types";

export type EngineState = "operational" | "degraded" | "offline";
export const MAX_ODDS_AGE_MIN = 45;

/** Derived only from what the API reports. A stale or missing feed always degrades the status. */
export function engineStatus(h: Health | null, apiError: string | null, gamesOnSlate: number | null, isToday: boolean): { state: EngineState; reasons: string[] } {
  if (apiError && !h) return { state: "offline", reasons: ["The API is not responding."] };
  if (!h) return { state: "offline", reasons: ["Connecting…"] };
  const reasons: string[] = [];
  if (apiError) reasons.push("The last health check failed; showing the previous one.");
  if (!h.production_model) reasons.push("No approved production model, so nothing can be published.");
  if (!h.odds_feed_configured) reasons.push("Odds feed is not configured.");
  const lastRun = h.recent_runs.find((r) => r.type !== "grading");
  if (lastRun?.status === "error") reasons.push(`The last analysis failed: ${lastRun.error ?? "see Learning Center"}`);
  if (isToday && (gamesOnSlate ?? 0) > 0 && !h.injury_report_fresh) {
    reasons.push(`Injury report is stale (fetched ${ago(h.latest_injury_fetched_at)}).`);
  }
  return { state: reasons.length ? "degraded" : "operational", reasons };
}

export function oddsFeedLabel(h: Health): { text: string; fresh: boolean } {
  if (!h.odds_feed_configured) return { text: "Not configured", fresh: false };
  const age = minutesSince(h.latest_odds_fetched_at);
  if (age == null) return { text: "No odds pulled yet", fresh: false };
  const fresh = age <= MAX_ODDS_AGE_MIN;
  return { text: `${fresh ? "Pulled" : "Stale: pulled"} ${ago(h.latest_odds_fetched_at)}`, fresh };
}
