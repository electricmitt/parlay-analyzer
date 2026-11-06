"use client";
import clsx from "clsx";
import { Bell, ChevronLeft, ChevronRight, Cpu, Menu, Play, RefreshCw, Search, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Headshot, TeamLogo } from "@/components/media";
import { Button, inputCls } from "@/components/ui";
import { api, fmtTime, longDate, refreshAll, shiftDate, todayET, useApi } from "@/lib/api";
import { useSlate } from "@/lib/slate";
import { oddsFeedLabel } from "@/lib/status";
import type { Health, Note, PlayerHit, RunSummary, Slate } from "@/lib/types";

function GlobalSearch({ slate }: { slate: Slate | null }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [debounced, setDebounced] = useState("");
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 180);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        input.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const players = useApi<PlayerHit[]>(debounced.length >= 2 ? `/api/players?q=${encodeURIComponent(debounced)}` : null);
  const needle = debounced.toLowerCase();
  const games = needle.length >= 2 ? (slate?.games ?? []).filter((g) =>
    [g.home.abbr, g.home.name, g.away.abbr, g.away.name].some((t) => t.toLowerCase().includes(needle))) : [];
  const go = (href: string) => { setOpen(false); setQ(""); router.push(href); };
  const showResults = open && debounced.length >= 2;

  return (
    <div className="relative min-w-0 flex-1 md:max-w-sm" onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setOpen(false); }}>
      <Search size={15} className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-ink-2" aria-hidden />
      <input
        ref={input} value={q} onFocus={() => setOpen(true)}
        onChange={(e) => { setQ(e.target.value); setOpen(true); }}
        onKeyDown={(e) => {
          if (e.key === "Escape") { setOpen(false); input.current?.blur(); }
          if (e.key === "Enter" && players.data?.[0]) go(`/players/${players.data[0].id}`);
        }}
        placeholder="Search players and teams"
        aria-label="Search players and teams"
        className={clsx(inputCls, "h-8 w-full pl-8")}
      />
      {showResults && (
        <div className="fade-in absolute top-full right-0 left-0 z-30 mt-1.5 max-h-80 overflow-auto rounded-xl border border-line bg-elevated p-1 shadow-2xl">
          {games.map((g) => (
            <button key={g.id} onClick={() => go(`/games/${g.id}`)} className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-neutral">
              <TeamLogo abbr={g.away.abbr} size={18} /> {g.away.abbr} @ {g.home.abbr} <TeamLogo abbr={g.home.abbr} size={18} />
              <span className="ml-auto text-xs text-ink-2">{longDate(g.date)}</span>
            </button>
          ))}
          {players.data?.map((p) => (
            <button key={p.id} onClick={() => go(`/players/${p.id}`)} className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-neutral">
              <Headshot id={p.id} name={p.name} size={24} /> {p.name}
              <span className="ml-auto text-xs text-ink-2">{p.team ?? "—"} · {p.position ?? "—"}</span>
            </button>
          ))}
          {!games.length && players.data?.length === 0 && <div className="px-2 py-3 text-center text-sm text-ink-2">No matching players, or teams on this slate.</div>}
          {players.error && <div className="px-2 py-3 text-center text-sm text-critical">{players.error}</div>}
        </div>
      )}
    </div>
  );
}

function Notifications() {
  const notes = useApi<Note[]>("/api/notifications?limit=20", { pollMs: 120_000 });
  const [open, setOpen] = useState(false);
  const [seen, setSeen] = useState(0);
  useEffect(() => setSeen(Number(localStorage.getItem("courtside:seen-note") ?? 0)), []);
  const newest = notes.data?.[0]?.id ?? 0;
  const toggle = () => {
    setOpen((o) => !o);
    localStorage.setItem("courtside:seen-note", String(newest));
    setSeen(newest);
  };
  return (
    <div className="relative" onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setOpen(false); }}>
      <button onClick={toggle} aria-label="Notifications" aria-expanded={open}
              className="relative flex size-8 items-center justify-center rounded-lg text-ink-2 transition-colors duration-150 hover:bg-elevated hover:text-ink">
        <Bell size={16} strokeWidth={1.7} aria-hidden />
        {newest > seen && <span className="absolute top-1.5 right-1.5 size-1.5 rounded-full bg-cyan" aria-label="New notifications" />}
      </button>
      {open && (
        <div tabIndex={-1} className="fade-in absolute top-full right-0 z-30 mt-1.5 max-h-96 w-80 max-w-[85vw] overflow-auto rounded-xl border border-line bg-elevated p-2 shadow-2xl">
          <div className="eyebrow px-1 pb-1.5">Notifications</div>
          {notes.data?.length ? notes.data.map((n) => (
            <div key={n.id} className="rounded-lg px-1 py-1.5 text-sm">
              <div className="font-medium text-ink">{n.title}</div>
              <div className="line-clamp-2 text-xs text-ink-2">{n.body}</div>
              <div className="mt-0.5 text-xs text-ink-2">{n.kind} · {fmtTime(n.created_at)}</div>
            </div>
          )) : <div className="px-1 py-3 text-sm text-ink-2">No notifications yet.</div>}
        </div>
      )}
    </div>
  );
}

/** Running analysis spends Odds API credits, so the cost is stated before anything happens. */
function RunDialog({ slate, health, date, onClose, onDone }: {
  slate: Slate | null; health: Health | null; date: string; onClose: () => void; onDone: (msg: string, ok: boolean) => void;
}) {
  const [running, setRunning] = useState(false);
  const upcoming = (slate?.games ?? []).filter((g) => !g.started).length;
  const markets = health?.odds_markets.length ?? 1;
  const cost = upcoming * markets;
  const credits = health?.odds_credits_remaining;

  async function run() {
    setRunning(true);
    try {
      const r = await api<RunSummary>(`/api/runs/analyze?date=${date}`, { method: "POST" });
      if (r.error) onDone(`Analysis failed: ${r.error}`, false);
      else if (r.analysis) {
        const a = r.analysis;
        const parts = [`${a.props_evaluated} props evaluated`, `${a.eligible} qualified`, `${a.recommended} published`];
        if (a.withdrawn) parts.push(`${a.withdrawn} withdrawn`);
        onDone(`Analysis complete: ${parts.join(", ")}.${r.warning ? ` ${r.warning}` : ""}`, true);
      } else onDone(r.warning ?? "Analysis finished without results.", false);
      refreshAll();
    } catch (e) {
      onDone((e as Error).message, false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-labelledby="run-title">
      <div className="fade-in w-full max-w-md rounded-2xl border border-line bg-elevated p-5 shadow-2xl">
        <div className="flex items-start justify-between gap-3">
          <h2 id="run-title" className="text-base font-medium">Run analysis for {longDate(date)}?</h2>
          {!running && <button onClick={onClose} aria-label="Close" className="text-ink-2 hover:text-ink"><X size={18} /></button>}
        </div>
        <div className="mt-3 space-y-2 text-sm text-ink-2">
          <p>Refreshes the schedule, box scores and injuries, then re-evaluates every prop. Picks can be published or withdrawn as a result.</p>
          {health?.odds_feed_configured && slate && !slate.schedule_loaded ? (
            <p>
              The schedule for this date hasn&apos;t loaded, so the cost isn&apos;t known yet: about{" "}
              <span className="num text-ink">{markets} {markets === 1 ? "credit" : "credits"} per game</span>, and a full slate can have 15 games.{" "}
              {credits != null ? <>About <span className="num text-ink">{credits}</span> remained after the last pull.</> : "Your balance is not known until the next pull."}
            </p>
          ) : health?.odds_feed_configured ? (
            <p>
              Pulling fresh odds for <span className="text-ink">{upcoming} upcoming {upcoming === 1 ? "game" : "games"}</span> costs about{" "}
              <span className="num text-ink">{cost} Odds API {cost === 1 ? "credit" : "credits"}</span>.{" "}
              {credits != null ? <>About <span className="num text-ink">{credits}</span> remained after the last pull.</> : "Your balance is not known until the next pull."}
            </p>
          ) : <p>No odds feed is configured, so this uses stored and manually entered odds.</p>}
        </div>
        {running && <div className="scan mt-4 h-0.5 rounded-full" role="progressbar" aria-label="Analysis in progress" />}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={running}>Cancel</Button>
          <Button onClick={run} disabled={running}>
            {running ? <><RefreshCw size={14} className="animate-spin" aria-hidden /> Analyzing…</> : "Run analysis"}
          </Button>
        </div>
      </div>
    </div>
  );
}

export function TopBar({ onOpenMenu }: { onOpenMenu: () => void }) {
  const { date, setDate, isToday } = useSlate();
  const health = useApi<Health>("/api/health", { pollMs: 60_000 });
  const slate = useApi<Slate>(`/api/slate?date=${date}`);
  const [dialog, setDialog] = useState(false);
  const [result, setResult] = useState<{ msg: string; ok: boolean } | null>(null);
  const h = health.data;
  const feed = h ? oddsFeedLabel(h) : null;

  return (
    <>
      <header className="sticky top-0 z-20 border-b border-line bg-page/90 backdrop-blur-md">
        <div className="flex h-14 items-center gap-2 px-3 lg:gap-3 lg:px-6">
          <button onClick={onOpenMenu} className="flex size-8 shrink-0 items-center justify-center rounded-lg text-ink-2 hover:bg-elevated hover:text-ink lg:hidden" aria-label="Open menu">
            <Menu size={18} aria-hidden />
          </button>

          <div className="hidden shrink-0 items-center gap-0.5 sm:flex">
            <button onClick={() => setDate(shiftDate(date, -1))} aria-label="Previous day" className="flex size-7 items-center justify-center rounded-md text-ink-2 hover:bg-elevated hover:text-ink"><ChevronLeft size={15} /></button>
            <input type="date" value={date} onChange={(e) => e.target.value && setDate(e.target.value)} aria-label="Slate date"
                   className={clsx(inputCls, "num h-8 w-[136px] px-2 text-xs")} />
            <button onClick={() => setDate(shiftDate(date, 1))} aria-label="Next day" className="flex size-7 items-center justify-center rounded-md text-ink-2 hover:bg-elevated hover:text-ink"><ChevronRight size={15} /></button>
            {!isToday && <button onClick={() => setDate(todayET())} className="ml-1 rounded-md px-1.5 py-1 text-xs text-[#7fb0fa] hover:bg-elevated">Today</button>}
          </div>

          <GlobalSearch slate={slate.data} />

          <div className="ml-auto flex shrink-0 items-center gap-1.5 lg:gap-3">
            {feed && (
              <span className="hidden items-center gap-1.5 text-xs text-ink-2 xl:flex" title="When odds were last pulled from The Odds API">
                <RefreshCw size={13} strokeWidth={1.7} aria-hidden className={feed.fresh ? "text-good" : "text-warning"} /> {feed.text}
              </span>
            )}
            {h && (
              <Link href="/learning" className="hidden items-center gap-1.5 text-xs text-ink-2 hover:text-ink lg:flex" title={h.production_model ? `Trained through ${h.production_model.trained_through}` : "No approved model"}>
                <Cpu size={13} strokeWidth={1.7} aria-hidden className={h.production_model ? "text-cyan" : "text-warning"} />
                {h.production_model ? <span className="num">v{h.production_model.version}</span> : "No model"}
              </Link>
            )}
            <Notifications />
            <Button onClick={() => setDialog(true)} disabled={!slate.data} className="h-8 px-2.5 text-xs" title="Run analysis for this slate">
              <Play size={13} aria-hidden /> <span className="hidden sm:inline">Run Analysis</span>
            </Button>
          </div>
        </div>
        <div className="flex items-center gap-2 border-t border-line px-3 py-1.5 sm:hidden">
          <input type="date" value={date} onChange={(e) => e.target.value && setDate(e.target.value)} aria-label="Slate date" className={clsx(inputCls, "num h-7 flex-1 px-2 text-xs")} />
          {!isToday && <button onClick={() => setDate(todayET())} className="text-xs text-[#7fb0fa]">Today</button>}
        </div>
        {result && (
          <div className={clsx("fade-in flex items-center justify-between gap-3 border-t border-line px-3 py-2 text-sm lg:px-6", result.ok ? "text-ink" : "text-critical")} role="status">
            {result.msg}
            <button onClick={() => setResult(null)} aria-label="Dismiss" className="shrink-0 text-ink-2 hover:text-ink"><X size={15} /></button>
          </div>
        )}
      </header>
      {dialog && (
        <RunDialog slate={slate.data} health={h} date={date} onClose={() => setDialog(false)}
                   onDone={(msg, ok) => { setResult({ msg, ok }); setDialog(false); }} />
      )}
    </>
  );
}
