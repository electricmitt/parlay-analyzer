"use client";
import { CalendarDays, CheckCircle2, ListChecks, Sparkles, TrendingUp } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { CalibrationChart } from "@/components/CalibrationChart";
import { EvHistogram, ParityScatter } from "@/components/charts";
import { EnginePanel } from "@/components/command/EnginePanel";
import { GameCard } from "@/components/command/GameCard";
import { MetricCard } from "@/components/command/MetricCard";
import { PickCard } from "@/components/command/PickCard";
import { PropTable } from "@/components/PropTable";
import { Button, Card, Empty, ErrorNote, inputCls, Section, Segmented, Skeleton } from "@/components/ui";
import { bookName, fmtClock, longDate, pct, useApi } from "@/lib/api";
import { useSlate } from "@/lib/slate";
import type { Block, Health, ModelInfo, Pred, Recs, Run, SettledRow, Slate } from "@/lib/types";

const PICKS_PREVIEW = 9;
const SORTS = [["ev", "Highest EV"], ["prob", "Highest probability"], ["unc", "Lowest uncertainty"]] as const;
type SortKey = (typeof SORTS)[number][0];
const uncertainty = (p: Pred) => (p.proj_p90 - p.proj_p10) / Math.max(p.line, 1);

function Filter({ label, value, onChange, options, format }: { label: string; value: string; onChange: (v: string) => void; options: string[]; format?: (v: string) => string }) {
  return (
    <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} className={`${inputCls} h-8 py-0 text-xs`}>
      <option value="">{label}: all</option>
      {options.map((o) => <option key={o} value={o}>{format ? format(o) : o}</option>)}
    </select>
  );
}

export default function CommandCenter() {
  const { date, isToday } = useSlate();
  const slate = useApi<Slate>(`/api/slate?date=${date}`);
  const recs = useApi<Recs>(`/api/recommendations?date=${date}`);
  const props = useApi<Pred[]>(`/api/props?date=${date}`);
  const health = useApi<Health>("/api/health", { pollMs: 60_000 });
  const runs = useApi<Run[]>("/api/runs?limit=30");
  const models = useApi<ModelInfo[]>("/api/models");
  const live = useApi<{ overall: Block }>("/api/performance?record_type=published");
  const settled = useApi<SettledRow[]>("/api/predictions/settled?record_type=published");

  const [sort, setSort] = useState<SortKey>("ev");
  const [player, setPlayer] = useState("");
  const [team, setTeam] = useState("");
  const [market, setMarket] = useState("");
  const [book, setBook] = useState("");
  const [calMarket, setCalMarket] = useState("pts");
  const [showAllPicks, setShowAllPicks] = useState(false);
  const [showAllProps, setShowAllProps] = useState(false);

  const picks = useMemo(() => recs.data?.picks ?? [], [recs.data]);
  const recentKeys = useMemo(() => [...new Set(picks.map((p) => `${p.player_id}:${p.market}`))].join(","), [picks]);
  const recent = useApi<Record<string, number[]>>(recentKeys ? `/api/recent-values?keys=${recentKeys}` : null);

  const shown = useMemo(() => {
    const needle = player.trim().toLowerCase();
    const out = picks.filter((p) => (!needle || p.player.toLowerCase().includes(needle)) && (!team || p.team === team || p.opponent === team)
      && (!market || p.market_label === market) && (!book || p.book === book));
    return out.sort((a, b) => sort === "ev" ? b.ev - a.ev : sort === "prob" ? b.model_prob - a.model_prob : uncertainty(a) - uncertainty(b));
  }, [picks, player, team, market, book, sort]);

  const t = slate.data?.totals;
  const allProps = props.data ?? [];
  const positive = props.data ? allProps.filter((p) => p.ev > 0).length : null;
  const dateRun = runs.data?.find((r) => r.date === date && r.type !== "grading" && r.status === "ok");
  const games = slate.data?.games ?? [];
  const analysed = !!dateRun;
  const asOf = dateRun ? `Analyzed ${fmtClock(dateRun.finished_at ?? dateRun.started_at)}` : games.length ? "Not analyzed yet" : "";
  const latestOdds = allProps.length ? allProps.reduce((m, p) => (p.odds_fetched_at > m ? p.odds_fetched_at : m), allProps[0].odds_fetched_at) : null;
  const injuriesFresh = health.data?.injury_report_fresh ?? false;
  const prod = models.data?.find((m) => m.status === "production");
  const calMarkets = Object.keys(prod?.metrics.markets ?? {});
  const calBins = prod?.metrics.markets?.[calMarket]?.calibration;
  const nonEligible = allProps.filter((p) => !p.eligible);
  const point = (p: Pred) => ({
    x: p.consensus_prob ?? p.novig_prob ?? p.implied_prob, y: p.model_prob,
    label: `${p.player} ${p.side} ${p.line} ${p.market_label}`,
    detail: `model ${pct(p.model_prob, 1)} · market ${pct(p.consensus_prob ?? p.novig_prob ?? p.implied_prob, 1)}`,
  });
  const scatterDomain: [number, number] = [0.2, 0.9];

  const settledRows = settled.data ?? [];
  const ptsSettled = settledRows.filter((r) => r.market === "pts");
  const actualMax = Math.max(10, ...ptsSettled.flatMap((r) => [r.proj_mean, r.actual])) * 1.05;

  return (
    <div className="space-y-6">
      <ErrorNote error={slate.error || health.error} />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricCard label="Games on slate" value={t?.games ?? null} Icon={CalendarDays} context={longDate(date)} freshness={isToday ? "Today" : undefined} />
        <MetricCard label="Props analyzed" value={t?.props_evaluated ?? null} Icon={ListChecks} context={health.data?.odds_feed_configured === false ? "Odds feed not configured" : "Priced lines evaluated"} freshness={asOf} />
        <MetricCard label="Positive EV opportunities" value={positive} Icon={TrendingUp} context={t ? `${t.eligible} passed every filter` : undefined} freshness={latestOdds ? `Odds as of ${fmtClock(latestOdds)}` : undefined} />
        <MetricCard label="Published picks" value={t?.published ?? null} Icon={CheckCircle2} context="Estimates, not guarantees" freshness={asOf} />
      </div>

      <EnginePanel health={health.data} healthError={health.error} runs={runs.data} models={models.data} live={live.data?.overall ?? null}
                   gamesOnSlate={t?.games ?? null} isToday={isToday} />

      <Section title="Slate" hint={longDate(date)}>
        {!slate.data && !slate.error ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-40" />)}</div>
        ) : games.length ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
            {games.map((g) => <GameCard key={g.id} game={g} injuriesFresh={injuriesFresh} />)}
          </div>
        ) : slate.data && (slate.data.schedule_loaded
          ? <Empty icon={<CalendarDays size={20} strokeWidth={1.5} />} title="No games scheduled for this slate." />
          : <Empty icon={<CalendarDays size={20} strokeWidth={1.5} />} title="The schedule for this date hasn't loaded yet.">It loads with the 9:00 AM ET run on game day, or when you use Run Analysis.</Empty>)}
      </Section>

      <Section title="AI-recommended player props" hint={recs.data?.disclaimer}>
        {picks.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <Segmented label="Sort picks" value={sort} onChange={setSort} options={SORTS} />
            <input value={player} onChange={(e) => setPlayer(e.target.value)} placeholder="Player" aria-label="Filter by player" className={`${inputCls} h-8 w-32 py-0 text-xs`} />
            <Filter label="Team" value={team} onChange={setTeam} options={[...new Set(picks.flatMap((p) => [p.team, p.opponent]).filter(Boolean) as string[])].sort()} />
            <Filter label="Market" value={market} onChange={setMarket} options={[...new Set(picks.map((p) => p.market_label))].sort()} />
            <Filter label="Book" value={book} onChange={setBook} options={[...new Set(picks.map((p) => p.book))].sort()} format={bookName} />
          </div>
        )}
        {!recs.data && !recs.error ? <Skeleton className="h-48" /> : shown.length ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {(showAllPicks ? shown : shown.slice(0, PICKS_PREVIEW)).map((p) => <PickCard key={p.id} p={p} recent={recent.data?.[`${p.player_id}:${p.market}`]} />)}
          </div>
        ) : picks.length ? (
          <Empty title="No picks match these filters." />
        ) : !games.length ? (
          <Empty icon={<Sparkles size={20} strokeWidth={1.5} />} title={slate.data?.schedule_loaded ? "No games, so no recommendations." : "Recommendations appear after the schedule loads."} />
        ) : !analysed ? (
          <Empty icon={<Sparkles size={20} strokeWidth={1.5} />} title="Your intelligence report is ready to generate.">
            Use Run Analysis in the top bar. The scheduled run happens at 9:00 AM ET.
          </Empty>
        ) : !allProps.length ? (
          <Empty icon={<Sparkles size={20} strokeWidth={1.5} />} title="No odds have been evaluated for this slate.">
            Lines may not be posted yet. You can also enter them on <Link href="/odds" className="text-[#7fb0fa] hover:underline">Odds Intelligence</Link>.
          </Empty>
        ) : (
          <Empty icon={<Sparkles size={20} strokeWidth={1.5} />} title="No qualifying opportunities detected.">
            {allProps.length} props were evaluated and none passed every filter. PASS is a valid outcome.
          </Empty>
        )}
      </Section>

      {shown.length > PICKS_PREVIEW && (
        <div className="-mt-3 text-center">
          <Button variant="ghost" onClick={() => setShowAllPicks((s) => !s)}>{showAllPicks ? "Show fewer picks" : `Show all ${shown.length} picks`}</Button>
        </div>
      )}

      {recs.data && recs.data.withdrawn.length > 0 && (
        <Section title="Withdrawn" hint="No longer meet the filters. Reconsider if you acted on these.">
          <Card><PropTable preds={recs.data.withdrawn} /></Card>
        </Section>
      )}

      <Section title="Intelligence visualizations">
        <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
          <Card title="Expected value distribution" eyebrow="This slate">
            {allProps.length ? <EvHistogram evs={allProps.map((p) => p.ev)} /> : <Empty>Appears once props are evaluated.</Empty>}
          </Card>
          <Card title="Model vs market probability" eyebrow="This slate">
            {allProps.length ? (
              <ParityScatter primary={allProps.filter((p) => p.eligible).map(point)} secondary={nonEligible.map(point)} domain={scatterDomain}
                             xLabel="market (no-vig)" yLabel="model" primaryLabel="Passed filters" secondaryLabel="Did not pass" />
            ) : <Empty>Appears once props are evaluated.</Empty>}
          </Card>
          <Card title="Historical calibration" eyebrow="Backtest, not live"
                action={calMarkets.length > 0 && (
                  <select aria-label="Calibration market" value={calMarket} onChange={(e) => setCalMarket(e.target.value)} className={`${inputCls} h-7 py-0 text-xs`}>
                    {calMarkets.map((m) => <option key={m} value={m}>{m.toUpperCase()}</option>)}
                  </select>
                )}>
            {calBins?.length ? <CalibrationChart bins={calBins} /> : <Empty>No backtest stored for this market.</Empty>}
          </Card>
          <Card title="Actual vs predicted points" eyebrow="Published picks, graded" className="xl:col-span-2">
            {ptsSettled.length ? (
              <ParityScatter
                primary={ptsSettled.map((r) => ({ x: r.proj_mean, y: r.actual, label: `${r.player} ${r.side} ${r.line}`, detail: `projected ${r.proj_mean.toFixed(1)} · actual ${r.actual} · ${r.result}` }))}
                domain={[0, Math.ceil(actualMax)]} xLabel="projected" yLabel="actual" primaryLabel={`Graded picks (n=${ptsSettled.length})`} format={(v) => String(Math.round(v))} />
            ) : <Empty>No published picks have been graded yet. This fills in as games finish.</Empty>}
          </Card>
          <Card title="Player performance trends" eyebrow="Research">
            <Empty action={<Link href="/players" className="text-sm text-[#7fb0fa] hover:underline">Open Player Research</Link>}>
              Each published pick above shows its last 10 games. Open a player for L5, L10, L20 and season trends.
            </Empty>
          </Card>
        </div>
      </Section>

      {allProps.length > 0 && (
        <Section title="All evaluated props" hint="Every priced line, including those that did not qualify. Select a row for reasoning."
                 action={<Button variant="ghost" onClick={() => setShowAllProps((s) => !s)}>{showAllProps ? "Hide table" : `Show ${allProps.length} lines`}</Button>}>
          {showAllProps && <Card className="fade-in"><PropTable preds={allProps} /></Card>}
        </Section>
      )}
    </div>
  );
}
