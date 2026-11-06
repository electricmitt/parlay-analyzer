"use client";
import clsx from "clsx";
import { AlertTriangle, CircleAlert, FlaskConical, Layers, Minus, Plus, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Headshot } from "@/components/media";
import { Badge, Card, Empty, ErrorNote, inputCls, PageHeader, Segmented, Skeleton } from "@/components/ui";
import { api, bookName, num, odds, pct, signedPct, useApi } from "@/lib/api";
import { useSlate } from "@/lib/slate";
import type { ParlayResult, Pred, Prefs } from "@/lib/types";

/** Selection criteria only. A mode narrows which legs are listed; it says nothing about results. */
const MODES = {
  conservative: { label: "Conservative", text: "Passed every filter, model probability at least 55%, low or moderate uncertainty.", test: (p: Pred) => p.eligible && p.model_prob >= 0.55 && p.risk_level !== "high" },
  balanced: { label: "Balanced", text: "Passed every filter.", test: (p: Pred) => p.eligible },
  aggressive: { label: "Aggressive", text: "Any priced line with positive EV, including lines that failed a filter. Those are not published picks.", test: (p: Pred) => p.ev > 0 },
} as const;
type Mode = keyof typeof MODES;
const RISK = { elevated: "warning", high: "serious", "very high": "critical" } as const;

function Row({ label, value, sub, big }: { label: string; value: React.ReactNode; sub?: React.ReactNode; big?: boolean }) {
  return (
    <div>
      <div className="text-xs text-ink-2">{label}</div>
      <div className={clsx("num text-ink", big ? "mt-0.5 text-2xl font-medium tracking-tight" : "mt-0.5 text-sm")}>{value}</div>
      {sub && <div className="num mt-0.5 text-xs text-ink-2">{sub}</div>}
    </div>
  );
}

export default function Parlay() {
  const { date } = useSlate();
  const props = useApi<Pred[]>(`/api/props?date=${date}`);
  const prefs = useApi<Prefs>("/api/preferences");
  const [mode, setMode] = useState<Mode>("balanced");
  const [bookChoice, setBookChoice] = useState<string | null>(null);
  const [legs, setLegs] = useState<Pred[]>([]);
  const [quoted, setQuoted] = useState("");
  const [result, setResult] = useState<ParlayResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const maxLegs = prefs.data?.max_parlay_legs ?? 3;

  // A leg from another slate cannot be part of this one.
  useEffect(() => { setLegs([]); }, [date]);

  const books = useMemo(() => [...new Set((props.data ?? []).map((p) => p.book))].sort(), [props.data]);
  // A parlay is one bet at one book, so start on the preferred book when it has prices.
  const preferred = prefs.data?.preferred_book;
  const book = bookChoice ?? (preferred && books.includes(preferred) ? preferred : "");

  const list = useMemo(() => {
    const open = (props.data ?? []).filter((p) => p.status === "active");
    const rows = open.filter(MODES[mode].test).filter((p) => !book || p.book === book).sort((a, b) => b.ev - a.ev);
    const seen = new Set<string>(); // with "All books", list each bet once at its best price
    return rows.filter((p) => {
      const k = `${p.player_id}|${p.market}|${p.side}|${p.line}`;
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    });
  }, [props.data, mode, book]);
  const selected = new Set(legs.map((l) => l.id));
  const quotedPrice = /^[+-]?\d+$/.test(quoted.trim()) ? Number(quoted) : null;

  useEffect(() => {
    if (legs.length < 2) { setResult(null); setError(null); return; }
    let stale = false;
    setBusy(true);
    const t = setTimeout(async () => {
      try {
        const r = await api<ParlayResult>("/api/parlay/analyze", { method: "POST", body: JSON.stringify({ prediction_ids: legs.map((l) => l.id), quoted_price: quotedPrice }) });
        if (!stale) { setResult(r); setError(null); }
      } catch (e) {
        if (!stale) { setResult(null); setError((e as Error).message); }
      } finally {
        if (!stale) setBusy(false);
      }
    }, 250);
    return () => { stale = true; clearTimeout(t); };
  }, [legs, quotedPrice]);

  const toggle = (p: Pred) => setLegs((ls) => ls.some((l) => l.id === p.id) ? ls.filter((l) => l.id !== p.id) : ls.length >= maxLegs ? ls : [...ls, p]);

  return (
    <div className="space-y-4">
      <PageHeader title={<span className="inline-flex items-center gap-2">Parlay Builder <Badge tone="info">Experimental</Badge></span>}>
        Estimates only: joint probabilities come from a correlation model that has not been walk-forward validated, and no parlay here is a published recommendation.
      </PageHeader>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,420px)]">
        <Card title="Available props" eyebrow={`${list.length} listed`} action={
          <div className="flex flex-wrap items-center gap-2">
            <Segmented label="Analysis mode" value={mode} onChange={setMode} options={Object.entries(MODES).map(([k, m]) => [k as Mode, m.label] as const)} />
            <select aria-label="Sportsbook" value={book} onChange={(e) => setBookChoice(e.target.value)} className={`${inputCls} h-8 py-0 text-xs`}>
              <option value="">All books</option>
              {books.map((b) => <option key={b} value={b}>{bookName(b)}</option>)}
            </select>
          </div>}>
          <p className="mb-3 text-xs text-ink-2">{MODES[mode].text}</p>
          <ErrorNote error={props.error} />
          {!props.data && !props.error ? <Skeleton className="h-48" /> : list.length ? (
            <ul className="divide-y divide-[var(--border)]">
              {list.map((p) => {
                const on = selected.has(p.id);
                const conflict = !on && legs.some((l) => l.player_id === p.player_id && l.market === p.market);
                const full = !on && (legs.length >= maxLegs || conflict);
                return (
                  <li key={p.id} className="flex items-center gap-3 py-2">
                    <Headshot id={p.player_id} name={p.player} size={34} />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm"><span className="font-medium">{p.player}</span> {p.side === "over" ? "Over" : "Under"} <span className="tnum">{p.line}</span> {p.market_label}</div>
                      <div className="num truncate text-xs text-ink-2">{p.game} · {bookName(p.book)} {odds(p.price)} · model {pct(p.model_prob)} · EV {signedPct(p.ev)}{!p.eligible ? " · failed a filter" : ""}</div>
                    </div>
                    <button onClick={() => toggle(p)} disabled={full} aria-pressed={on} aria-label={`${on ? "Remove" : "Add"} ${p.player}`} title={conflict ? "This player already has a leg in this market" : full ? `Your maximum is ${maxLegs} legs (Settings)` : undefined}
                            className={clsx("flex size-7 shrink-0 items-center justify-center rounded-lg border transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-35", on ? "border-series-1 bg-series-1/20 text-ink" : "border-line text-ink-2 hover:bg-elevated hover:text-ink")}>
                      {on ? <Minus size={14} /> : <Plus size={14} />}
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : (
            <Empty icon={<Layers size={20} strokeWidth={1.5} />} title="No qualifying opportunities detected.">
              {(props.data?.length ?? 0) > 0 ? "No priced lines meet this mode's criteria." : "No lines have been evaluated for this slate."}
            </Empty>
          )}
        </Card>

        <div className="space-y-3 lg:sticky lg:top-20 lg:self-start">
          <Card title="Parlay" eyebrow={`${legs.length} of ${maxLegs} legs`}>
            {legs.length ? (
              <ul className="space-y-1.5">
                {legs.map((l) => (
                  <li key={l.id} className="flex items-center gap-2 rounded-lg bg-page-2 px-2.5 py-1.5 text-sm">
                    <span className="min-w-0 flex-1 truncate">{l.player} {l.side === "over" ? "O" : "U"} <span className="tnum">{l.line}</span> {l.market_label}</span>
                    <span className="num text-xs text-ink-2">{bookName(l.book)} {odds(l.price)}</span>
                    <button onClick={() => toggle(l)} aria-label={`Remove ${l.player}`} className="text-ink-2 hover:text-ink"><X size={14} /></button>
                  </li>
                ))}
              </ul>
            ) : <p className="text-sm text-ink-2">Add at least two legs to see the analysis.</p>}
            {legs.length >= 2 && (
              <label className="mt-3 block text-xs text-ink-2">Price quoted by your book (American)
                <input value={quoted} onChange={(e) => setQuoted(e.target.value)} placeholder="+450" inputMode="numeric" className={`${inputCls} num mt-1 w-full`} />
              </label>
            )}
          </Card>

          <ErrorNote error={error} />
          {legs.length >= 2 && !result && busy && <Skeleton className="h-52" />}
          {result && (
            <div className={clsx("space-y-3 transition-opacity duration-150", busy && "opacity-60")}>
              <Card title="Analysis" action={<Badge tone={RISK[result.risk_level as keyof typeof RISK]}>{result.risk_level} risk</Badge>}>
                <div className="grid grid-cols-2 gap-4">
                  <Row big label="Estimated joint probability" value={pct(result.joint_prob, 1)} sub={`range ${pct(result.joint_low, 1)}–${pct(result.joint_high, 1)}`} />
                  <Row big label="Estimated EV" value={result.ev == null ? "Needs price" : <span className={result.ev > 0 ? "text-good-text" : "text-critical"}>{signedPct(result.ev)}</span>}
                       sub={result.ev == null ? "Enter your book's quote" : `range ${signedPct(result.ev_low)} to ${signedPct(result.ev_high)}`} />
                  <Row label="Combined odds" value={result.price ? odds(result.price.american) : "—"} sub={result.price ? (result.price.source === "quoted" ? "as you entered" : "multiplied; confirm with your book") : `multiplied would be ${num(result.multiplied_decimal, 2)}x, which your book won't pay`} />
                  <Row label="If legs were independent" value={pct(result.independent_prob, 1)} sub="for comparison only" />
                </div>
                <p className="mt-3 text-xs leading-relaxed text-ink-2">{result.sensitivity_note}</p>
              </Card>

              {result.warnings.length > 0 && (
                <div className="space-y-1.5 rounded-xl border border-warning/25 bg-warning/5 p-3" role="status">
                  {result.warnings.map((w, i) => (
                    <div key={i} className="flex gap-2 text-sm">
                      {w.level === "serious" ? <AlertTriangle size={14} className="mt-0.5 shrink-0 text-serious" aria-hidden /> : <CircleAlert size={14} className="mt-0.5 shrink-0 text-warning" aria-hidden />}
                      <span>{w.message}</span>
                    </div>
                  ))}
                </div>
              )}

              {result.pairs.length > 0 && (
                <Card title="Same-game correlations">
                  <ul className="space-y-1.5 text-sm">
                    {result.pairs.map((c, i) => (
                      <li key={i} className="flex items-baseline justify-between gap-3">
                        <span className="min-w-0 text-ink-2">{c.a} {c.a_market} / {c.b} {c.b_market} <span className="text-xs">({c.basis})</span></span>
                        <span className="num shrink-0">{c.sufficient_history ? `${c.rho >= 0 ? "+" : ""}${c.rho.toFixed(2)} · ${c.shared_games} g` : `unknown · ${c.shared_games} g`}</span>
                      </li>
                    ))}
                  </ul>
                </Card>
              )}

              <p className="flex gap-2 text-xs leading-relaxed text-ink-2"><FlaskConical size={13} className="mt-0.5 shrink-0" aria-hidden /> {result.method}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
