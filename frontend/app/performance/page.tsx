"use client";
import { useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CalibrationChart } from "@/components/CalibrationChart";
import { axis, ParityScatter } from "@/components/charts";
import { Badge, Card, Empty, ErrorNote, PageHeader, Segmented, Skeleton, Stat, Td, Th } from "@/components/ui";
import { num, pct, signedPct, useApi } from "@/lib/api";
import type { Block, SettledRow } from "@/lib/types";

type BtMarket = {
  n: number; mae_model: number; mae_l10: number; mae_season: number; brier_model: number; brier_naive: number;
  brier_diff_ci95: [number, number]; ece_model: number; ece_naive: number; coverage_80: number; base_rate_over: number;
  calibration: { bin: string; n: number; mean_pred: number; obs_rate: number }[];
};
type Perf = {
  record_type: string; overall: Block; today: Block; last_7_days: Block; last_30_days: Block;
  by_market?: Record<string, Block>; by_book?: Record<string, Block>; by_model_version?: Record<string, Block>;
  by_ev_band?: Record<string, Block>; by_prob_band?: Record<string, Block>;
  daily_series: { date: string; units: number; cum_units: number; n: number }[];
  backtest: { model: string; label: string; date_range?: string[]; n_predictions: number; markets: Record<string, BtMarket>; minutes_mae?: number; gate?: { pass: boolean; reasons: string[] } } | null;
};

const TYPES = [
  ["published", "Published picks"],
  ["paper", "Paper (all evaluated props)"],
  ["withdrawn", "Withdrawn picks"],
] as const;

function BreakdownTable({ title, data }: { title: string; data?: Record<string, Block> }) {
  if (!data || !Object.keys(data).length) return null;
  return (
    <Card title={title}>
      <table className="w-full">
        <thead className="border-b border-line"><tr><Th /><Th right>N</Th><Th right>W-L-P</Th><Th right>Win%</Th><Th right>Units</Th><Th right>ROI</Th><Th right>Exp. ROI</Th><Th right>Brier</Th></tr></thead>
        <tbody>
          {Object.entries(data).map(([k, b]) => (
            <tr key={k} className="border-b border-line">
              <Td>{k}</Td><Td right>{b.n}</Td><Td right>{b.wins}-{b.losses}-{b.pushes}</Td><Td right>{pct(b.win_rate, 1)}</Td>
              <Td right>{num(b.units, 2)}</Td><Td right>{signedPct(b.roi)}</Td><Td right>{signedPct(b.expected_roi)}</Td><Td right>{num(b.brier, 3)}</Td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

export default function Performance() {
  const [rt, setRt] = useState<(typeof TYPES)[number][0]>("published");
  const { data, error } = useApi<Perf>(`/api/performance?record_type=${rt}`);
  const settled = useApi<SettledRow[]>(`/api/predictions/settled?record_type=${rt}`);
  const rows = settled.data ?? [];
  const top = Math.ceil(Math.max(10, ...rows.flatMap((r) => [r.proj_mean, r.actual])) * 1.05);
  const o = data?.overall;
  const smallSample = o && o.n < 100;

  return (
    <div className="space-y-6">
      <PageHeader title="Performance">Live records only: graded against official box scores, flat 1-unit stakes. Backtests are shown separately below and never mixed in.</PageHeader>
      <Segmented label="Record type" value={rt} onChange={setRt} options={TYPES} />
      <ErrorNote error={error} />
      {!data && !error && <Skeleton className="h-40" />}
      {o && (
        <>
          {smallSample && <div className="text-sm"><Badge tone="warning">Small sample</Badge> <span className="text-ink-2">{o.n} graded bets. Results this small are dominated by variance; do not read skill into them.</span></div>}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-6">
            <Stat label="Record (W-L-P)" value={`${o.wins}-${o.losses}-${o.pushes}`} hint={`${o.voids} void`} />
            <Stat label="Win rate" value={pct(o.win_rate, 1)} />
            <Stat label="Profit (units)" value={num(o.units, 2)} />
            <Stat label="ROI" value={signedPct(o.roi)} hint={`model expected ${signedPct(o.expected_roi)}`} />
            <Stat label="Max drawdown" value={`${num(o.max_drawdown, 2)}u`} />
            <Stat label="Brier (model / market)" value={<span className="text-base">{num(o.brier, 3)} / {num(o.brier_market, 3)}</span>} hint={`avg CLV ${signedPct(o.avg_clv)}`} />
          </div>
          <div className="grid grid-cols-3 gap-3">
            {(["today", "last_7_days", "last_30_days"] as const).map((k) => (
              <Stat key={k} label={k.replaceAll("_", " ")} value={`${num(data![k].units, 2)}u`} hint={`${data![k].wins}-${data![k].losses}-${data![k].pushes} · ROI ${signedPct(data![k].roi)}`} />
            ))}
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Cumulative profit (units)">
              {data!.daily_series.length ? (
                <div className="h-56">
                  <ResponsiveContainer>
                    <LineChart data={data!.daily_series} margin={{ top: 8, right: 12, left: -12, bottom: 0 }}>
                      <CartesianGrid vertical={false} stroke="var(--grid)" />
                      <XAxis dataKey="date" {...axis} minTickGap={24} tickFormatter={(d: string) => d.slice(5)} />
                      <YAxis {...axis} />
                      <ReferenceLine y={0} stroke="var(--axis)" />
                      <Tooltip contentStyle={{ background: "var(--elevated)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12, color: "var(--ink)" }}
                               formatter={(v) => [`${(v as number).toFixed(2)}u`, "cumulative"]} />
                      <Line dataKey="cum_units" stroke="var(--series-1)" strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : <Empty>No graded records yet.</Empty>}
            </Card>
            <Card title="Calibration (live)">
              {o.calibration?.length ? <CalibrationChart bins={o.calibration} /> : <Empty>Needs graded records.</Empty>}
            </Card>
          </div>
          <Card title="Actual vs predicted" eyebrow={`${TYPES.find(([k]) => k === rt)?.[1]} · all markets`}>
            {rows.length ? (
              <ParityScatter primaryLabel={`Graded (n=${rows.length})`} xLabel="projected" yLabel="actual" domain={[0, top]} format={(v) => String(Math.round(v))}
                primary={rows.map((r) => ({ x: r.proj_mean, y: r.actual, label: `${r.player} ${r.side} ${r.line} ${r.market_label}`, detail: `projected ${r.proj_mean.toFixed(1)} · actual ${r.actual} · ${r.result}` }))} />
            ) : <Empty>No graded records yet.</Empty>}
          </Card>
          <div className="grid gap-4 lg:grid-cols-2">
            <BreakdownTable title="By market" data={data!.by_market} />
            <BreakdownTable title="By sportsbook" data={data!.by_book} />
            <BreakdownTable title="By EV band" data={data!.by_ev_band} />
            <BreakdownTable title="By model probability band" data={data!.by_prob_band} />
            <BreakdownTable title="By model version" data={data!.by_model_version} />
          </div>
        </>
      )}

      <Card title={<>Backtest — {data?.backtest?.model ?? "no production model"} <Badge tone="info">backtest, not live</Badge></>}>
        {data?.backtest?.markets ? (
          <>
            <p className="mb-3 text-xs text-ink-2">
              {data.backtest.label}. Walk-forward, out-of-sample {data.backtest.date_range?.join(" → ")} · {data.backtest.n_predictions} predictions ·
              minutes MAE {num(data.backtest.minutes_mae)}. Proxy line = floor(last-10 average) + 0.5. The naive baseline is the smoothed
              last-10 hit rate. No prices were available, so this measures forecast quality, <b>not</b> profitability.
            </p>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[800px]">
                <thead className="border-b border-line"><tr><Th>Market</Th><Th right>N</Th><Th right>MAE model / L10 / season</Th><Th right>Brier model / naive</Th><Th right>Δ Brier 95% CI</Th><Th right>ECE model / naive</Th><Th right>80% PI coverage</Th></tr></thead>
                <tbody>
                  {Object.entries(data.backtest.markets).map(([m, r]) => (
                    <tr key={m} className="border-b border-line">
                      <Td>{m}</Td><Td right>{r.n}</Td>
                      <Td right>{num(r.mae_model, 2)} / {num(r.mae_l10, 2)} / {num(r.mae_season, 2)}</Td>
                      <Td right>{num(r.brier_model, 4)} / {num(r.brier_naive, 4)}</Td>
                      <Td right>[{num(r.brier_diff_ci95[0], 4)}, {num(r.brier_diff_ci95[1], 4)}]</Td>
                      <Td right>{num(r.ece_model, 3)} / {num(r.ece_naive, 3)}</Td>
                      <Td right>{pct(r.coverage_80, 1)}</Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-4 grid gap-4 md:grid-cols-3">
              {Object.entries(data.backtest.markets).slice(0, 3).map(([m, r]) => (
                <div key={m}><div className="eyebrow mb-1">{m.toUpperCase()} calibration (backtest)</div><CalibrationChart bins={r.calibration} /></div>
              ))}
            </div>
          </>
        ) : <Empty>No backtest available. Run <code>courtside train</code>.</Empty>}
      </Card>
    </div>
  );
}
