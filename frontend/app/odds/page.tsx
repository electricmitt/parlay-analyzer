"use client";
import { useEffect, useState } from "react";
import { PropTable } from "@/components/PropTable";
import { Button, Card, Empty, ErrorNote, inputCls, PageHeader, Section, Stat } from "@/components/ui";
import { ago, api, fmtTime, num, pct, refreshAll, signedPct, useApi } from "@/lib/api";
import { useSlate } from "@/lib/slate";
import { oddsFeedLabel } from "@/lib/status";
import type { Game, Health, Pred } from "@/lib/types";

type Meta = { markets: { key: string; label: string }[]; books: string[] };
type Proj = { player_id: string; player: string; team_id: string };

export default function OddsIntelligence() {
  const { date, setDate } = useSlate();
  const health = useApi<Health>("/api/health", { pollMs: 60_000 });
  const props = useApi<Pred[]>(`/api/props?date=${date}`);
  const slate = useApi<{ games: Game[] }>(`/api/slate?date=${date}`);
  const meta = useApi<Meta>("/api/meta");
  const [gameId, setGameId] = useState("");
  const game = useApi<{ projections: Proj[] }>(gameId ? `/api/games/${gameId}` : null);
  const [form, setForm] = useState({ player_id: "", market: "pts", book: "hardrockbet", line: "", over: "", under: "" });
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const upcoming = (slate.data?.games ?? []).filter((g) => !g.started);

  useEffect(() => { setGameId(upcoming[0]?.id ?? ""); }, [slate.data]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null); setMsg(null);
    try {
      const r = await api<{ snapshot_id: number; analysis: { analysis?: { recommended: number; props_evaluated: number }; warning?: string } }>(
        "/api/odds/manual", {
          method: "POST",
          body: JSON.stringify({
            game_id: gameId, player_id: form.player_id, market: form.market, book: form.book, line: parseFloat(form.line),
            over_price: form.over ? parseInt(form.over) : null, under_price: form.under ? parseInt(form.under) : null,
          }),
        });
      const a = r.analysis?.analysis;
      setMsg(`Saved snapshot #${r.snapshot_id}. ${r.analysis?.warning ?? ""} ${a ? `Re-analysis: ${a.props_evaluated} props evaluated, ${a.recommended} published.` : ""}`);
      setForm({ ...form, line: "", over: "", under: "" });
      refreshAll();
    } catch (e) {
      setErr((e as Error).message);
    } finally { setBusy(false); }
  }

  const input = `${inputCls} mt-1 w-full`;
  const h = health.data;
  const feed = h ? oddsFeedLabel(h) : null;
  const all = props.data ?? [];
  const gap = (p: Pred) => p.model_prob - (p.consensus_prob ?? p.novig_prob ?? p.implied_prob);
  const gaps = [...all].sort((a, b) => Math.abs(gap(b)) - Math.abs(gap(a))).slice(0, 8);
  return (
    <div className="space-y-6">
      <PageHeader title="Odds Intelligence">Feed status, every priced line on this slate, and manual odds entry.</PageHeader>
      <ErrorNote error={err || slate.error || props.error} />
      {msg && <div className="fade-in rounded-lg border border-line bg-surface p-3 text-sm" role="status">{msg}</div>}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Odds feed" value={<span className="font-sans text-sm">{feed?.text ?? "—"}</span>} hint={h?.odds_markets.join(", ")} />
        <Stat label="Credits left at last pull" value={h?.odds_credits_remaining ?? "—"} hint={h?.odds_credits_checked_at ? ago(h.odds_credits_checked_at) : "Known after the next pull"} />
        <Stat label="Scheduled pulls" value={<span className="font-sans text-sm">{h?.odds_fetch_runs.join(", ") ?? "—"}</span>} />
        <Stat label="Lines on this slate" value={all.length} />
      </div>

      <Section title="Largest model vs market gaps" hint="A big gap is often missing information, not an edge. Gaps over 15 points are blocked from publishing.">
        {gaps.length ? (
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            {gaps.map((p) => (
              <div key={p.id} className="rounded-xl border border-line bg-surface px-3 py-2.5">
                <div className="truncate text-sm">{p.player}</div>
                <div className="text-xs text-ink-2">{p.side} {p.line} {p.market_label}</div>
                <div className="num mt-1 text-sm">{signedPct(gap(p))} <span className="text-xs text-ink-2">model {pct(p.model_prob)} · proj {num(p.proj_mean)}</span></div>
              </div>
            ))}
          </div>
        ) : <Empty>No lines have been evaluated for this slate.</Empty>}
      </Section>

      <Section title="Price board" hint="Select a row for reasoning.">
        <Card>{all.length ? <PropTable preds={all} /> : <Empty>No lines have been evaluated for this slate.</Empty>}</Card>
      </Section>

      <Section title="Manual odds entry" hint="Enter the exact line and both prices from your sportsbook app. Entries are stored append-only with a timestamp and go stale after the configured window. One side works, but both are needed to remove the book's margin. Pre-game only.">
      <Card className="max-w-3xl">
        <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm">Date<br /><input type="date" className={input} value={date} onChange={(e) => setDate(e.target.value)} /></label>
          <label className="text-sm">Game<br />
            <select className={input} value={gameId} onChange={(e) => setGameId(e.target.value)} required>
              {upcoming.length === 0 && <option value="">No upcoming games</option>}
              {upcoming.map((g) => <option key={g.id} value={g.id}>{g.away.abbr} @ {g.home.abbr} — {fmtTime(g.start_time)}</option>)}
            </select>
          </label>
          <label className="text-sm">Player<br />
            <select className={input} value={form.player_id} onChange={(e) => setForm({ ...form, player_id: e.target.value })} required>
              <option value="">{game.data?.projections.length ? "Select player" : "Run analysis first to load rosters"}</option>
              {game.data?.projections.map((p) => <option key={p.player_id} value={p.player_id}>{p.player}</option>)}
            </select>
          </label>
          <label className="text-sm">Market<br />
            <select className={input} value={form.market} onChange={(e) => setForm({ ...form, market: e.target.value })}>
              {meta.data?.markets.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
            </select>
          </label>
          <label className="text-sm">Sportsbook<br />
            <select className={input} value={form.book} onChange={(e) => setForm({ ...form, book: e.target.value })}>
              {meta.data?.books.map((b) => <option key={b}>{b}</option>)}
            </select>
          </label>
          <label className="text-sm">Line<br /><input className={input} required type="number" step="0.5" value={form.line} onChange={(e) => setForm({ ...form, line: e.target.value })} placeholder="24.5" /></label>
          <label className="text-sm">Over price (American)<br /><input className={input} type="number" value={form.over} onChange={(e) => setForm({ ...form, over: e.target.value })} placeholder="-115" /></label>
          <label className="text-sm">Under price (American)<br /><input className={input} type="number" value={form.under} onChange={(e) => setForm({ ...form, under: e.target.value })} placeholder="-105" /></label>
          <div className="sm:col-span-2"><Button type="submit" disabled={busy || !gameId}>{busy ? "Saving & analyzing…" : "Save and re-analyze"}</Button></div>
        </form>
      </Card>
      </Section>
    </div>
  );
}
