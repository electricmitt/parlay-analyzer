"use client";
import clsx from "clsx";
import { ArrowUp, Sparkles, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { inputCls } from "@/components/ui";
import { answer, SUGGESTIONS, type Answer, type AnswerBlock } from "@/lib/assistant";
import { bookName, odds } from "@/lib/api";
import { useSlate } from "@/lib/slate";

type Turn = { id: number; q: string; a?: Answer; error?: string };

function Blocks({ blocks }: { blocks: AnswerBlock[] }) {
  return (
    <div className="space-y-2">
      {blocks.map((b, i) => {
        if (b.kind === "text") return <p key={i} className="leading-relaxed text-ink">{b.text}</p>;
        if (b.kind === "link") return <Link key={i} href={b.href} className="text-[#7fb0fa] hover:underline">{b.label}</Link>;
        if (b.kind === "list") return (
          <div key={i}>
            {b.title && <div className="eyebrow mb-1">{b.title}</div>}
            <ul className="list-disc space-y-0.5 pl-4 text-ink-2">{b.items.map((x, j) => <li key={j}>{x}</li>)}</ul>
          </div>
        );
        if (b.kind === "stats") return (
          <dl key={i} className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 rounded-lg bg-page-2 p-2">
            {b.rows.map(([k, v]) => [<dt key={k} className="text-ink-2">{k}</dt>, <dd key={`${k}v`} className="num text-right text-ink">{v}</dd>])}
          </dl>
        );
        return (
          <div key={i} className="divide-y divide-[var(--border)] rounded-lg bg-page-2">
            {b.items.map((p) => (
              <Link key={p.id} href={`/players/${p.player_id}`} className="block px-2 py-1.5 hover:bg-neutral">
                <div className="text-ink">{p.player} <span className="font-medium">{p.side.toUpperCase()} {p.line}</span> {p.market_label}</div>
                <div className="num text-xs text-ink-2">{bookName(p.book)} {odds(p.price)}{b.note ? ` · ${b.note(p)}` : ""}</div>
              </Link>
            ))}
          </div>
        );
      })}
    </div>
  );
}

export function Assistant() {
  const { date } = useSlate();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [turns, open]);

  async function ask(text: string) {
    const question = text.trim();
    if (!question || busy) return;
    const id = Date.now();
    setQ("");
    setBusy(true);
    setTurns((t) => [...t, { id, q: question }]);
    try {
      const a = await answer(question, date);
      setTurns((t) => t.map((x) => (x.id === id ? { ...x, a } : x)));
    } catch (e) {
      setTurns((t) => t.map((x) => (x.id === id ? { ...x, error: (e as Error).message } : x)));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {open && (
        <div role="dialog" aria-label="Courtside Intelligence" className="fade-in fixed right-3 bottom-16 left-3 z-40 flex max-h-[75vh] flex-col overflow-hidden rounded-2xl border border-line bg-elevated shadow-2xl sm:left-auto sm:w-[400px]">
          <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
            <div>
              <div className="flex items-center gap-1.5 text-sm font-medium"><Sparkles size={14} className="text-cyan" aria-hidden /> Courtside Intelligence</div>
              <div className="mt-0.5 text-xs text-ink-2">Rule-based: looks up verified app data for the selected slate. It isn&apos;t a language model, so it can&apos;t answer freeform questions.</div>
            </div>
            <button onClick={() => setOpen(false)} aria-label="Close assistant" className="text-ink-2 hover:text-ink"><X size={17} /></button>
          </div>
          <div className="min-h-32 flex-1 space-y-4 overflow-auto px-4 py-3 text-sm" aria-live="polite">
            {!turns.length && (
              <div className="space-y-1.5">
                {SUGGESTIONS.map((s) => (
                  <button key={s} onClick={() => ask(s)} className="block w-full rounded-lg border border-line px-2.5 py-1.5 text-left text-xs text-ink-2 transition-colors duration-150 hover:bg-neutral hover:text-ink">{s}</button>
                ))}
              </div>
            )}
            {turns.map((t) => (
              <div key={t.id} className="space-y-2">
                <div className="ml-auto w-fit max-w-[85%] rounded-xl bg-series-1/15 px-3 py-1.5 text-ink">{t.q}</div>
                {t.a && <div className="fade-in space-y-2"><Blocks blocks={t.a.blocks} /><div className="text-xs text-ink-2">Source: {t.a.source}</div></div>}
                {t.error && <p className="text-critical">Couldn&apos;t reach the data: {t.error}</p>}
                {!t.a && !t.error && <div className="scan h-0.5 w-24 rounded-full" role="progressbar" aria-label="Looking up data" />}
              </div>
            ))}
            <div ref={end} />
          </div>
          <form onSubmit={(e) => { e.preventDefault(); ask(q); }} className="flex items-center gap-2 border-t border-line p-2">
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask about this slate or a player" aria-label="Ask Courtside Intelligence" className={clsx(inputCls, "min-w-0 flex-1")} />
            <button type="submit" disabled={busy || !q.trim()} aria-label="Send" className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-series-1 text-white transition-opacity duration-150 disabled:opacity-40"><ArrowUp size={15} /></button>
          </form>
        </div>
      )}
      <button
        onClick={() => setOpen((o) => !o)}
        aria-label={open ? "Close Courtside Intelligence" : "Open Courtside Intelligence"}
        aria-expanded={open}
        className="fixed right-3 bottom-3 z-40 flex h-10 items-center gap-2 rounded-full border border-line bg-elevated px-3.5 text-xs font-medium text-ink shadow-xl transition-all duration-150 hover:border-series-1/60 hover:shadow-[0_0_18px_rgb(59_130_246/0.2)]"
      >
        <Sparkles size={14} className="text-cyan" aria-hidden /> <span className="hidden sm:inline">Courtside Intelligence</span>
      </button>
    </>
  );
}
