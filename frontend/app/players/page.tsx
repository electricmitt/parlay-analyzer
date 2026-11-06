"use client";
import { GitCompareArrows, Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { TrendLine } from "@/components/charts";
import { Headshot } from "@/components/media";
import { Card, Empty, ErrorNote, inputCls, PageHeader, Segmented, Td, Th } from "@/components/ui";
import { num, useApi } from "@/lib/api";
import { mean, played, seasonGames } from "@/lib/insights";
import type { LogRow, PlayerDetail, PlayerHit } from "@/lib/types";

const WINDOWS = [["5", "L5"], ["10", "L10"], ["20", "L20"], ["season", "Season"]] as const;
type Win = (typeof WINDOWS)[number][0];
const STATS = [["pts", "Points"], ["reb", "Rebounds"], ["ast", "Assists"], ["fg3m", "3PM"], ["minutes", "Minutes"]] as const;
type StatKey = (typeof STATS)[number][0];
const windowRows = (log: LogRow[], w: Win) => (w === "season" ? seasonGames(log) : played(log).slice(0, Number(w)));

function useSearch(q: string) {
  const [debounced, setDebounced] = useState(q);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 180);
    return () => clearTimeout(t);
  }, [q]);
  return useApi<PlayerHit[]>(debounced.length >= 2 ? `/api/players?q=${encodeURIComponent(debounced)}` : null);
}

function PlayerPicker({ label, selected, onSelect }: { label: string; selected: PlayerHit | null; onSelect: (p: PlayerHit | null) => void }) {
  const [q, setQ] = useState("");
  const { data } = useSearch(q);
  if (selected) {
    return (
      <div className="flex items-center gap-2.5 rounded-lg border border-line bg-page-2 px-2.5 py-1.5">
        <Headshot id={selected.id} name={selected.name} size={28} />
        <Link href={`/players/${selected.id}`} className="min-w-0 truncate text-sm font-medium hover:underline">{selected.name}</Link>
        <span className="text-xs text-ink-2">{selected.team}</span>
        <button onClick={() => onSelect(null)} className="ml-auto text-xs text-ink-2 hover:text-ink">Change</button>
      </div>
    );
  }
  return (
    <div className="relative">
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={label} aria-label={label} className={`${inputCls} w-full`} />
      {q.trim().length >= 2 && data && (
        <div className="absolute top-full z-10 mt-1 max-h-60 w-full overflow-auto rounded-lg border border-line bg-elevated p-1 shadow-xl">
          {data.map((p) => (
            <button key={p.id} onClick={() => { onSelect(p); setQ(""); }} className="flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-sm hover:bg-neutral">
              {p.name} <span className="ml-auto text-xs text-ink-2">{p.team}</span>
            </button>
          ))}
          {!data.length && <div className="px-2 py-2 text-sm text-ink-2">No players found.</div>}
        </div>
      )}
    </div>
  );
}

function Compare() {
  const [a, setA] = useState<PlayerHit | null>(null);
  const [b, setB] = useState<PlayerHit | null>(null);
  const [win, setWin] = useState<Win>("10");
  const [stat, setStat] = useState<StatKey>("pts");
  const da = useApi<PlayerDetail>(a ? `/api/players/${a.id}` : null);
  const db = useApi<PlayerDetail>(b ? `/api/players/${b.id}` : null);
  const rowsA = da.data ? windowRows(da.data.game_log, win) : [];
  const rowsB = db.data ? windowRows(db.data.game_log, win) : [];
  const trend = (rows: LogRow[]) => [...rows].reverse().map((r) => ({ date: r.date, opp: r.opp, [stat]: r[stat] }));
  // Both panels share one y-scale, so the two players can be compared by eye.
  const top = Math.max(1, ...[...rowsA, ...rowsB].map((r) => r[stat] as number));
  const statLabel = STATS.find(([k]) => k === stat)![1];
  return (
    <Card title="Compare two players" eyebrow="Side by side" action={<GitCompareArrows size={15} className="text-ink-2" aria-hidden />}>
      <div className="grid gap-2 sm:grid-cols-2">
        <PlayerPicker label="First player" selected={a} onSelect={setA} />
        <PlayerPicker label="Second player" selected={b} onSelect={setB} />
      </div>
      {da.data && db.data && (
        <div className="fade-in mt-4 space-y-4">
          <div className="flex flex-wrap gap-2">
            <Segmented label="Window" value={win} onChange={setWin} options={WINDOWS} />
            <Segmented label="Stat" value={stat} onChange={setStat} options={STATS} />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[480px]">
              <thead className="border-b border-line"><tr><Th>Average</Th><Th right>G</Th>{STATS.map(([k, l]) => <Th key={k} right>{l}</Th>)}</tr></thead>
              <tbody>
                {[[a, rowsA], [b, rowsB]].map(([p, rows]) => (
                  <tr key={(p as PlayerHit).id} className="border-b border-line">
                    <Td>{(p as PlayerHit).name}</Td>
                    <Td right>{(rows as LogRow[]).length}</Td>
                    {STATS.map(([k]) => <Td key={k} right>{num(mean((rows as LogRow[]).map((r) => r[k] as number)))}</Td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {[[a, rowsA], [b, rowsB]].map(([p, rows]) => (
              <div key={(p as PlayerHit).id}>
                <div className="mb-1 text-xs text-ink-2">{(p as PlayerHit).name} · {statLabel}</div>
                {(rows as LogRow[]).length ? <TrendLine data={trend(rows as LogRow[])} dataKey={stat} label={statLabel} height={170} domain={[0, Math.ceil(top * 1.05)]} /> : <Empty>No games in this window.</Empty>}
              </div>
            ))}
          </div>
        </div>
      )}
      <ErrorNote error={da.error || db.error} />
    </Card>
  );
}

export default function Players() {
  const [q, setQ] = useState("");
  const { data, error } = useSearch(q);
  const active = q.trim().length >= 2;
  return (
    <div className="space-y-5">
      <PageHeader title="Player Research">Game logs, trends, line history and projections.</PageHeader>
      <div className="relative max-w-md">
        <Search size={15} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-ink-2" aria-hidden />
        <input autoFocus placeholder="Search players" aria-label="Search players" value={q} onChange={(e) => setQ(e.target.value)} className={`${inputCls} w-full py-2 pl-9`} />
      </div>
      <ErrorNote error={error} />
      {active && (
        data?.length ? (
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {data.map((p) => (
              <Link key={p.id} href={`/players/${p.id}`} className="lift flex items-center gap-3 rounded-xl border border-line bg-surface p-3">
                <Headshot id={p.id} name={p.name} size={40} />
                <span className="min-w-0"><span className="block truncate text-sm font-medium">{p.name}</span><span className="block text-xs text-ink-2">{p.team ?? "—"} · {p.position ?? "—"}</span></span>
              </Link>
            ))}
          </div>
        ) : data && <Empty title="No players found." />
      )}
      <Compare />
    </div>
  );
}
