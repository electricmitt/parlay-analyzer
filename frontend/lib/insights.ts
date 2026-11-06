import type { LogRow, PlayerDetail } from "./types";

export const played = (log: LogRow[]) => log.filter((r) => !r.dnp && r.minutes > 0);
export const seasonGames = (log: LogRow[]) => {
  const rows = played(log);
  return rows.length ? rows.filter((r) => r.season === rows[0].season) : [];
};
export const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);

/** Shot volume per 36 minutes: a usage proxy from the box score, not the official usage rate. */
export const volumePer36 = (r: LogRow) => (r.minutes > 0 ? ((r.fga + 0.44 * r.fta + r.tov) / r.minutes) * 36 : 0);

const STATS: [keyof LogRow, string][] = [["pts", "points"], ["reb", "rebounds"], ["ast", "assists"], ["fg3m", "threes"]];

/** Plain statements computed from the game log. Nothing is inferred beyond the arithmetic shown. */
export function playerInsights(d: PlayerDetail): string[] {
  const rows = played(d.game_log);
  const out: string[] = [];
  if (rows.length < 5) return [`Only ${rows.length} played games on record, too few to describe a trend.`];
  const l5 = rows.slice(0, 5);
  const base = rows.slice(5, 25);
  if (base.length >= 5) {
    for (const [k, label] of STATS) {
      const a = mean(l5.map((r) => r[k] as number))!;
      const b = mean(base.map((r) => r[k] as number))!;
      if (b >= 1.5 && Math.abs(a - b) / b >= 0.15) {
        out.push(`${label[0].toUpperCase()}${label.slice(1)} ${a > b ? "up" : "down"}: ${a.toFixed(1)} over the last 5 games vs ${b.toFixed(1)} over the prior ${base.length}.`);
      }
    }
    const m5 = mean(l5.map((r) => r.minutes))!;
    const mb = mean(base.map((r) => r.minutes))!;
    if (Math.abs(m5 - mb) >= 2.5) out.push(`Minutes ${m5 > mb ? "rising" : "falling"}: ${m5.toFixed(1)} over the last 5 vs ${mb.toFixed(1)} over the prior ${base.length}.`);
    const v5 = mean(l5.map(volumePer36))!;
    const vb = mean(base.map(volumePer36))!;
    if (vb > 0 && Math.abs(v5 - vb) / vb >= 0.12) out.push(`Shot volume per 36 ${v5 > vb ? "up" : "down"}: ${v5.toFixed(1)} vs ${vb.toFixed(1)}.`);
  }
  const missed = d.game_log.slice(0, 10).filter((r) => r.dnp).length;
  if (missed) out.push(`Did not play in ${missed} of the last ${Math.min(10, d.game_log.length)} team games on record.`);
  const lp = d.latest_projection?.markets.pts;
  if (lp) {
    const l10 = mean(rows.slice(0, 10).map((r) => r.pts))!;
    out.push(`Latest points projection ${lp.mean.toFixed(1)} (80% range ${lp.p10.toFixed(0)}–${lp.p90.toFixed(0)}) vs a last-10 average of ${l10.toFixed(1)}.`);
  }
  if (!out.length) out.push("Recent production and minutes are in line with the prior sample.");
  return out;
}
