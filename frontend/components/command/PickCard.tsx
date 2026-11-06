"use client";
import { ChevronDown } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { RangeBar, Sparkline } from "@/components/charts";
import { Headshot } from "@/components/media";
import { PropDetail } from "@/components/PropTable";
import { Badge } from "@/components/ui";
import { bookName, fmtClock, num, odds, pct, signedPct } from "@/lib/api";
import type { Pred } from "@/lib/types";

const RISK = { low: "good", moderate: "warning", high: "serious" } as const;

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-ink-2">{label}</div>
      <div className="num mt-0.5 text-sm text-ink">{value}</div>
    </div>
  );
}

export function PickCard({ p, recent }: { p: Pred; recent?: number[] }) {
  const [open, setOpen] = useState(false);
  const hits = recent?.filter((v) => (p.side === "over" ? v > p.line : v < p.line)).length;
  const reasoning = p.factors.slice(0, 2).join(". ");
  return (
    <article className="lift fade-in flex flex-col rounded-xl border border-line bg-surface p-4">
      <div className="flex items-start gap-3">
        <Headshot id={p.player_id} name={p.player} size={44} />
        <div className="min-w-0 flex-1">
          <Link href={`/players/${p.player_id}`} className="block truncate text-sm font-medium hover:underline">{p.player}</Link>
          <div className="truncate text-xs text-ink-2">
            {p.team && p.opponent ? `${p.team} vs ${p.opponent}` : p.game} · {fmtClock(p.start_time)}
          </div>
        </div>
        <div className="text-right">
          <div className={`num text-xl leading-none font-medium ${p.ev > 0 ? "text-good-text" : "text-critical"}`}>{signedPct(p.ev)}</div>
          <div className="mt-1 text-xs text-ink-2">est. EV</div>
        </div>
      </div>

      <div className="mt-3 flex items-baseline gap-2">
        <span className="text-lg font-medium tracking-tight">{p.side === "over" ? "Over" : "Under"} <span className="tnum">{p.line}</span> {p.market_label}</span>
      </div>
      <div className="num mt-0.5 text-xs text-ink-2">{bookName(p.book)} {odds(p.price)} · odds as of {fmtClock(p.odds_fetched_at)}</div>

      <div className="mt-3 grid grid-cols-3 gap-2">
        <Figure label="Model win prob" value={pct(p.model_prob, 1)} />
        <Figure label="Implied by price" value={pct(p.implied_prob, 1)} />
        <Figure label="Fair price" value={odds(p.fair_odds)} />
      </div>

      <div className="mt-3">
        <div className="mb-0.5 flex items-center justify-between text-xs text-ink-2">
          <span className="num">Proj {num(p.proj_mean)} · 80% range {num(p.proj_p10, 0)}–{num(p.proj_p90, 0)}</span>
          <Badge tone={RISK[p.risk_level as keyof typeof RISK] ?? "neutral"}>{p.risk_level} uncertainty</Badge>
        </div>
        <RangeBar p10={p.proj_p10} p50={p.proj_p50} p90={p.proj_p90} line={p.line} />
      </div>

      <div className="mt-2.5 flex items-center justify-between gap-3">
        {recent ? <Sparkline values={recent} line={p.line} label={`${p.player} ${p.market_label}, last ${recent.length} games`} /> : <span />}
        {recent && recent.length > 0 && <span className="num text-right text-xs text-ink-2">{p.side === "over" ? "Over" : "Under"} in {hits} of last {recent.length}</span>}
      </div>

      {reasoning && <p className="mt-2.5 line-clamp-2 text-xs leading-relaxed text-ink-2">{reasoning}.</p>}

      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} className="mt-2 inline-flex w-fit items-center gap-1 text-xs text-[#7fb0fa] hover:underline">
        Full reasoning <ChevronDown size={12} className={`transition-transform duration-150 ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      {open && <div className="fade-in mt-2 border-t border-line pt-3 text-sm"><PropDetail p={p} /></div>}
    </article>
  );
}
