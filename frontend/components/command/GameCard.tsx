"use client";
import { ArrowUpRight, CircleAlert } from "lucide-react";
import Link from "next/link";
import { TeamLogo } from "@/components/media";
import { Badge } from "@/components/ui";
import { fmtClock } from "@/lib/api";
import type { Game, InjuryChip } from "@/lib/types";

const FINAL = "STATUS_FINAL";
const SUFFIX = /^(jr\.?|sr\.?|ii|iii|iv|v)$/i;
const surname = (name: string) => name.split(" ").filter((w) => !SUFFIX.test(w)).slice(-1)[0] ?? name;
const notable = (xs: InjuryChip[] = []) => xs.filter((i) => /out|doubtful|questionable/i.test(i.status));

function TeamRow({ abbr, record, score, side }: { abbr: string; record?: string | null; score: number | null; side: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <TeamLogo abbr={abbr} size={26} />
      <span className="text-sm font-medium">{abbr}</span>
      <span className="num text-xs text-ink-2" title="Regular-season record from stored results">{record ?? ""}</span>
      <span className="sr-only">{side}</span>
      {score != null && <span className="num ml-auto text-sm">{score}</span>}
    </div>
  );
}

export function GameCard({ game: g, injuriesFresh }: { game: Game; injuriesFresh: boolean }) {
  const inj = [...notable(g.injuries?.away), ...notable(g.injuries?.home)];
  const out = inj.filter((i) => /out/i.test(i.status)).length;
  const status = g.status === FINAL ? "Final" : g.started ? "In progress" : fmtClock(g.start_time);
  return (
    <Link href={`/games/${g.id}`} className="lift group flex flex-col gap-2.5 rounded-xl border border-line bg-surface p-3.5">
      <div className="flex items-center justify-between text-xs text-ink-2">
        <span className="num">{status}</span>
        {g.decision === "PICKS" ? <Badge tone="good">{g.published} {g.published === 1 ? "pick" : "picks"}</Badge>
          : g.decision === "PASS" ? <Badge>PASS</Badge> : <span>No odds yet</span>}
      </div>
      <div className="space-y-1.5">
        <TeamRow abbr={g.away.abbr} record={g.away_record} score={g.away.score} side="away" />
        <TeamRow abbr={g.home.abbr} record={g.home_record} score={g.home.score} side="home" />
      </div>
      <div className="flex items-center justify-between gap-2 border-t border-line pt-2 text-xs text-ink-2">
        <span className="num">{g.props_evaluated ?? 0} lines · {g.eligible ?? 0} qualify</span>
        <span className="inline-flex items-center gap-0.5 text-[#7fb0fa] opacity-80 transition-opacity duration-150 group-hover:opacity-100">Analyze <ArrowUpRight size={12} aria-hidden /></span>
      </div>
      {!injuriesFresh ? (
        <div className="text-xs text-ink-2">Injury report is stale</div>
      ) : inj.length > 0 ? (
        <div className="flex items-start gap-1.5 text-xs text-ink-2" title={inj.map((i) => `${i.player} (${i.status})`).join(", ")}>
          <CircleAlert size={12} className="mt-px shrink-0 text-warning" aria-hidden />
          <span className="line-clamp-1">{out > 0 && `${out} out · `}{inj.slice(0, 3).map((i) => surname(i.player)).join(", ")}{inj.length > 3 ? ` +${inj.length - 3}` : ""}</span>
        </div>
      ) : null}
    </Link>
  );
}
