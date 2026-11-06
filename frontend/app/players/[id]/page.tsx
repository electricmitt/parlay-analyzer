"use client";
import { use, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { axis, TrendLine } from "@/components/charts";
import { Headshot, TeamLogo } from "@/components/media";
import { PropTable } from "@/components/PropTable";
import { Badge, Card, Empty, ErrorNote, inputCls, Segmented, Skeleton, Stat, Td, Th } from "@/components/ui";
import { fmtTime, num, useApi } from "@/lib/api";
import { mean, played, playerInsights, seasonGames, volumePer36 } from "@/lib/insights";
import type { Game, LogRow, PlayerDetail } from "@/lib/types";

type Dist = { histogram: { value: number; p: number }[] };

const WINDOWS = [["5", "L5"], ["10", "L10"], ["20", "L20"], ["season", "Season"]] as const;
type Win = (typeof WINDOWS)[number][0];
const STATS = [["pts", "Points"], ["reb", "Rebounds"], ["ast", "Assists"], ["fg3m", "3PM"]] as const;
const DIST_MARKETS = [["pts", "Points"], ["reb", "Rebounds"], ["ast", "Assists"], ["fg3m", "3PM"], ["pra", "PRA"]] as const;
const LINE_MARKETS = [...STATS, ["pra", "PRA"]] as const;
const tooltipStyle = { background: "var(--elevated)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--ink)", fontSize: 12 };
type LineMarket = (typeof LINE_MARKETS)[number][0];
const statValue = (r: LogRow, k: LineMarket) => (k === "pra" ? r.pts + r.reb + r.ast : r[k]);

function rowsFor(log: LogRow[], w: Win) {
  return w === "season" ? seasonGames(log) : played(log).slice(0, Number(w));
}

/** How the selected line would have done over the chosen window. A description of the past, not a forecast. */
function LineHistory({ log, win }: { log: LogRow[]; win: Win }) {
  const [market, setMarket] = useState<LineMarket>("pts");
  const rows = rowsFor(log, win);
  const avg = mean(rows.map((r) => statValue(r, market)));
  const [line, setLine] = useState("");
  const value = line === "" ? (avg != null ? Math.floor(avg) + 0.5 : 0) : Number(line);
  const over = rows.filter((r) => statValue(r, market) > value).length;
  const under = rows.filter((r) => statValue(r, market) < value).length;
  const chart = [...rows].reverse().map((r) => ({ date: r.date, opp: r.opp, v: statValue(r, market), hit: statValue(r, market) > value }));
  return (
    <Card title="Performance against a line" eyebrow="History" action={
      <div className="flex items-center gap-2">
        <select aria-label="Market" value={market} onChange={(e) => setMarket(e.target.value as LineMarket)} className={`${inputCls} h-7 py-0 text-xs`}>
          {LINE_MARKETS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <input aria-label="Line" type="number" step="0.5" value={line === "" ? value : line} onChange={(e) => setLine(e.target.value)} className={`${inputCls} num h-7 w-20 py-0 text-xs`} />
      </div>}>
      {rows.length ? (
        <>
          <div className="num mb-2 text-sm">
            Over <span className="text-ink">{over}</span> · Under <span className="text-ink">{under}</span>
            <span className="text-ink-2"> of {rows.length} games at {value}</span>
          </div>
          <div className="h-44">
            <ResponsiveContainer>
              <BarChart data={chart} margin={{ top: 6, right: 6, left: -20, bottom: 0 }} barCategoryGap={2}>
                <CartesianGrid vertical={false} stroke="var(--grid)" />
                <XAxis dataKey="date" {...axis} tickFormatter={(d: string) => d.slice(5)} interval="preserveStartEnd" minTickGap={24} />
                <YAxis {...axis} allowDecimals={false} />
                <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "var(--neutral)" }} formatter={(v) => [v as number, market.toUpperCase()]}
                         labelFormatter={(d, pl) => `${d} vs ${pl?.[0]?.payload?.opp ?? ""}`} />
                <ReferenceLine y={value} stroke="var(--ink)" strokeDasharray="4 3" />
                <Bar dataKey="v" maxBarSize={18} radius={[4, 4, 0, 0]} shape={(props: unknown) => {
                  const { x, y, width, height, payload } = props as { x: number; y: number; width: number; height: number; payload: { hit: boolean } };
                  return <rect x={x} y={y} width={width} height={height} rx={Math.min(3, width / 2)} fill={payload.hit ? "var(--series-1)" : "#566172"} />;
                }} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-1 flex gap-3 text-xs text-ink-2">
            <span className="flex items-center gap-1.5"><span className="size-2 rounded-sm bg-series-1" /> Over the line</span>
            <span className="flex items-center gap-1.5"><span className="size-2 rounded-sm bg-[#566172]" /> At or under</span>
          </div>
        </>
      ) : <Empty>No games in this window.</Empty>}
    </Card>
  );
}

function Matchup({ log, nextOpp }: { log: LogRow[]; nextOpp?: string }) {
  const opponents = useMemo(() => [...new Set(played(log).map((r) => r.opp))].sort(), [log]);
  const [picked, setPicked] = useState("");
  const opp = picked || (nextOpp && opponents.includes(nextOpp) ? nextOpp : opponents[0]);
  const rows = played(log).filter((r) => r.opp === opp);
  return (
    <Card title="Matchup statistics" eyebrow={nextOpp ? `Next opponent: ${nextOpp}` : "By opponent"} action={
      <select aria-label="Opponent" value={opp ?? ""} onChange={(e) => setPicked(e.target.value)} className={`${inputCls} h-7 py-0 text-xs`}>
        {opponents.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>}>
      {rows.length ? (
        <div className="overflow-x-auto">
          <div className="mb-2 flex items-center gap-2 text-sm"><TeamLogo abbr={opp!} size={20} /> {rows.length} {rows.length === 1 ? "game" : "games"} vs {opp}{rows.length < 3 && <Badge tone="warning">Small sample</Badge>}</div>
          <table className="w-full">
            <thead className="border-b border-line"><tr><Th>Avg</Th><Th right>MIN</Th><Th right>PTS</Th><Th right>REB</Th><Th right>AST</Th><Th right>3PM</Th></tr></thead>
            <tbody><tr className="border-b border-line"><Td>vs {opp}</Td>{(["minutes", "pts", "reb", "ast", "fg3m"] as const).map((k) => <Td key={k} right>{num(mean(rows.map((r) => r[k])))}</Td>)}</tr></tbody>
          </table>
        </div>
      ) : <Empty>No games against this opponent on record.</Empty>}
    </Card>
  );
}

export default function PlayerPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, error } = useApi<PlayerDetail>(`/api/players/${id}`);
  const [win, setWin] = useState<Win>("10");
  const [stat, setStat] = useState<(typeof STATS)[number][0]>("pts");
  const [dm, setDm] = useState<(typeof DIST_MARKETS)[number][0]>("pts");
  const lp = data?.latest_projection;
  const dist = useApi<Dist>(lp ? `/api/players/${id}/distribution?market=${dm}` : null);
  const next = useApi<{ game: Game }>(lp ? `/api/games/${lp.game_id}` : null);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <div className="space-y-3"><Skeleton className="h-20" /><Skeleton className="h-64" /></div>;

  const rows = rowsFor(data.game_log, win);
  const trend = [...rows].reverse().map((r) => ({ date: r.date, opp: r.opp, pts: r.pts, reb: r.reb, ast: r.ast, fg3m: r.fg3m, minutes: r.minutes, volume: Math.round(volumePer36(r) * 10) / 10 }));
  const statLabel = STATS.find(([k]) => k === stat)![1];
  const statAvg = mean(rows.map((r) => r[stat]));
  const nextGame = next.data?.game;
  const team = data.player.team;
  const nextOpp = nextGame && !nextGame.started ? (nextGame.home.abbr === team ? nextGame.away.abbr : nextGame.home.abbr) : undefined;
  const dnps = data.game_log.filter((r) => r.dnp);
  const allAverages = WINDOWS.map(([k, l]) => ({ k, l, rows: rowsFor(data.game_log, k) }));

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center gap-4">
        <Headshot id={data.player.id} name={data.player.name} size={64} />
        <div className="min-w-0">
          <h1 className="text-xl font-medium tracking-tight">{data.player.name}</h1>
          <div className="mt-0.5 flex flex-wrap items-center gap-2 text-sm text-ink-2">
            {team && <span className="inline-flex items-center gap-1.5"><TeamLogo abbr={team} size={18} /> {team}</span>}
            <span>{data.player.position ?? "—"}</span>
            {data.injury && <Badge tone={data.injury.status === "Out" ? "critical" : "warning"}>{data.injury.status}{data.injury.detail ? `: ${data.injury.detail}` : ""}</Badge>}
          </div>
        </div>
        <div className="ml-auto"><Segmented label="Window" value={win} onChange={setWin} options={WINDOWS} /></div>
      </header>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {([...STATS, ["minutes", "Minutes"]] as const).slice(0, 5).map(([k, l]) => (
          <Stat key={k} label={`${l} avg`} value={num(mean(rows.map((r) => r[k as "pts"])))} hint={`${rows.length} ${rows.length === 1 ? "game" : "games"}`} />
        ))}
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <Card title={`${statLabel} trend`} eyebrow={`${rows.length} games`} className="lg:col-span-2" action={
          <Segmented label="Stat" value={stat} onChange={setStat} options={STATS} />}>
          {trend.length ? <TrendLine data={trend} dataKey={stat} label={statLabel} reference={statAvg != null ? { y: Math.round(statAvg * 10) / 10, label: `avg ${statAvg.toFixed(1)}` } : undefined} /> : <Empty>No games in this window.</Empty>}
        </Card>
        <Card title="Insights" eyebrow="Computed from the game log">
          <ul className="space-y-2 text-sm leading-relaxed text-ink-2">
            {playerInsights(data).map((t, i) => <li key={i}>{t}</li>)}
          </ul>
        </Card>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Card title="Minutes trend" eyebrow={`${rows.length} games`}>
          {trend.length ? <TrendLine data={trend} dataKey="minutes" label="Minutes" height={170} /> : <Empty>No games in this window.</Empty>}
        </Card>
        <Card title="Usage trend" eyebrow="Proxy: (FGA + 0.44 FTA + TOV) per 36, not official usage rate">
          {trend.length ? <TrendLine data={trend} dataKey="volume" label="Volume per 36" height={170} /> : <Empty>No games in this window.</Empty>}
        </Card>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <LineHistory log={data.game_log} win={win} />
        <Card title="Projected distribution" eyebrow="Next game" action={
          <select aria-label="Distribution market" value={dm} onChange={(e) => setDm(e.target.value as typeof dm)} className={`${inputCls} h-7 py-0 text-xs`}>
            {DIST_MARKETS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>}>
          {lp && dist.data ? (
            <>
              <div className="h-44">
                <ResponsiveContainer>
                  <BarChart data={dist.data.histogram} margin={{ top: 20, right: 8, left: -16, bottom: 0 }} barCategoryGap={1}>
                    <CartesianGrid vertical={false} stroke="var(--grid)" />
                    <XAxis dataKey="value" {...axis} />
                    <YAxis {...axis} tickFormatter={(v: number) => `${Math.round(v * 100)}%`} />
                    <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "var(--neutral)" }}
                             formatter={(v) => [`${((v as number) * 100).toFixed(1)}%`, "probability"]} labelFormatter={(v) => `exactly ${v}`} />
                    <ReferenceLine x={Math.round(lp.markets[dm]?.p50 ?? 0)} stroke="var(--ink-2)" strokeDasharray="4 3"
                      label={{ value: "median", fill: "var(--ink-2)", fontSize: 11, position: "top" }} />
                    <Bar dataKey="p" fill="var(--series-1)" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-ink-2">
                Monte Carlo simulation. 80% interval {num(lp.markets[dm]?.p10, 0)}–{num(lp.markets[dm]?.p90, 0)}. Projected minutes {num(lp.minutes)} ± {num(lp.sd_minutes)}. Generated {fmtTime(lp.created_at)}.
              </p>
            </>
          ) : lp ? <Skeleton className="h-44" /> : <Empty>No upcoming-game projection yet.</Empty>}
        </Card>
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <Card title="Averages by window" className="lg:col-span-1">
          <table className="w-full">
            <thead className="border-b border-line"><tr><Th /><Th right>G</Th><Th right>MIN</Th><Th right>PTS</Th><Th right>REB</Th><Th right>AST</Th></tr></thead>
            <tbody>
              {allAverages.map(({ k, l, rows: rs }) => (
                <tr key={k} className="border-b border-line"><Td>{l}</Td><Td right>{rs.length}</Td>{(["minutes", "pts", "reb", "ast"] as const).map((m) => <Td key={m} right>{num(mean(rs.map((r) => r[m])))}</Td>)}</tr>
              ))}
              {lp && <tr><Td className="text-[#7fb0fa]">Proj</Td><Td right>—</Td><Td right>{num(lp.minutes)}</Td>{(["pts", "reb", "ast"] as const).map((m) => <Td key={m} right>{num(lp.markets[m]?.p50, 0)}</Td>)}</tr>}
            </tbody>
          </table>
        </Card>
        <Matchup log={data.game_log} nextOpp={nextOpp} />
        <Card title="Availability" eyebrow="Injury report and missed games">
          <div className="space-y-2 text-sm">
            {data.injury_history.length ? (
              <ul className="space-y-1.5">
                {[...data.injury_history].reverse().slice(0, 5).map((h, i) => (
                  <li key={i} className="text-ink-2"><span className="text-ink">{h.status}</span>{h.detail ? `: ${h.detail}` : ""}<div className="text-xs">First seen {fmtTime(h.first_seen)}</div></li>
                ))}
              </ul>
            ) : <p className="text-ink-2">Not on any injury report we have recorded.</p>}
            <p className="text-xs text-ink-2">
              {dnps.length ? `${dnps.length} DNP in the last ${data.game_log.length} box scores, most recently ${dnps[0].date}.` : `No DNP in the last ${data.game_log.length} box scores.`} Injury history starts when we began recording reports, and games missed while inactive may not appear in box scores.
            </p>
          </div>
        </Card>
      </div>

      <Card title="Settled prop evaluations">
        {data.prop_history.length ? <PropTable preds={data.prop_history} /> : <Empty>No settled props for this player yet.</Empty>}
      </Card>

      <Card title="Game log">
        <div className="max-h-96 overflow-auto">
          <table className="w-full min-w-[640px]">
            <thead className="sticky top-0 border-b border-line bg-surface"><tr><Th>Date</Th><Th>Opp</Th><Th right>MIN</Th><Th right>PTS</Th><Th right>REB</Th><Th right>AST</Th><Th right>3PM</Th><Th right>STL</Th><Th right>BLK</Th><Th right>TOV</Th><Th right>PF</Th></tr></thead>
            <tbody>
              {data.game_log.map((r) => (
                <tr key={r.game_id} className="border-b border-line">
                  <Td className="num">{r.date}</Td><Td>{r.home ? "vs" : "@"} {r.opp}</Td>
                  {r.dnp ? <Td className="text-ink-2">DNP</Td> : (<>
                    <Td right>{r.minutes}</Td><Td right>{r.pts}</Td><Td right>{r.reb}</Td><Td right>{r.ast}</Td><Td right>{r.fg3m}</Td>
                    <Td right>{r.stl}</Td><Td right>{r.blk}</Td><Td right>{r.tov}</Td><Td right>{r.pf}</Td></>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
