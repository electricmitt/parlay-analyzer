"use client";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { useReducedMotion } from "./ui";

export const axis = { stroke: "var(--axis)", tick: { fill: "var(--ink-2)", fontSize: 11 }, tickLine: false };
const percent = (v: number) => `${Math.round(v * 100)}%`;

function Tip({ children }: { children: React.ReactNode }) {
  return <div className="rounded-lg border border-line bg-elevated px-2.5 py-1.5 text-xs text-ink shadow-xl">{children}</div>;
}

/** Last-N values with the betting line. Single series, so no legend; the caption beside it names it. */
export function Sparkline({ values, line, label, width = 112, height = 32 }: { values: number[]; line?: number; label: string; width?: number; height?: number }) {
  if (values.length < 2) return <span className="text-xs text-ink-2">Not enough games</span>;
  const lo = Math.min(...values, line ?? Infinity);
  const hi = Math.max(...values, line ?? -Infinity);
  const x = (i: number) => 3 + (i * (width - 6)) / (values.length - 1);
  const y = (v: number) => height - 3 - ((v - lo) / (hi - lo || 1)) * (height - 6);
  const last = values[values.length - 1];
  return (
    <svg width={width} height={height} role="img" aria-label={`${label}: ${values.join(", ")}`} className="overflow-visible">
      {line != null && <line x1={0} x2={width} y1={y(line)} y2={y(line)} stroke="var(--ink-2)" strokeWidth={1} strokeDasharray="3 3" />}
      <polyline fill="none" stroke="var(--series-1)" strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round"
                points={values.map((v, i) => `${x(i)},${y(v)}`).join(" ")} />
      {values.map((v, i) => (
        <circle key={i} cx={x(i)} cy={y(v)} r={i === values.length - 1 ? 2.5 : 5} fill={i === values.length - 1 ? "var(--series-1)" : "transparent"}>
          <title>{v}</title>
        </circle>
      ))}
      <title>{`${label}. Latest ${last}`}</title>
    </svg>
  );
}

/** Where the line sits inside the projected 80% range. */
export function RangeBar({ p10, p50, p90, line }: { p10: number; p50: number; p90: number; line: number }) {
  const lo = Math.min(p10, line) * 0.92;
  const hi = Math.max(p90, line) * 1.08 || 1;
  const pos = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;
  return (
    <div className="relative h-4" role="img" aria-label={`80% projected range ${p10.toFixed(0)} to ${p90.toFixed(0)}, median ${p50.toFixed(0)}, line ${line}`}>
      <div className="absolute top-1/2 right-0 left-0 h-px -translate-y-1/2 bg-line" />
      <div className="absolute top-1/2 h-1 -translate-y-1/2 rounded-full bg-series-1/45" style={{ left: pos(p10), width: `${((p90 - p10) / (hi - lo)) * 100}%` }} />
      <div className="absolute top-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-series-1 ring-2 ring-surface" style={{ left: pos(p50) }} title={`Median ${p50.toFixed(0)}`} />
      <div className="absolute top-0 h-4 w-px bg-ink" style={{ left: pos(line) }} title={`Line ${line}`} />
    </div>
  );
}

export function EvHistogram({ evs }: { evs: number[] }) {
  const reduced = useReducedMotion();
  const size = 0.02;
  const counts = new Map<number, number>();
  for (const e of evs) {
    const k = Math.floor(e / size);
    counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  const keys = [...counts.keys()];
  const data = [];
  for (let k = Math.min(...keys); k <= Math.max(...keys); k++) {
    data.push({ k, from: k * size, to: (k + 1) * size, n: counts.get(k) ?? 0, positive: k >= 0 });
  }
  return (
    <div className="h-52">
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 6, right: 6, left: -20, bottom: 0 }} barCategoryGap={2}>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey="from" {...axis} tickFormatter={percent} interval="preserveStartEnd" />
          <YAxis {...axis} allowDecimals={false} />
          <Tooltip cursor={{ fill: "var(--neutral)" }} content={({ payload }) => {
            const d = payload?.[0]?.payload;
            return d ? <Tip>EV {percent(d.from)} to {percent(d.to)}: <span className="num">{d.n}</span> {d.n === 1 ? "prop" : "props"}</Tip> : null;
          }} />
          <Bar dataKey="n" radius={[4, 4, 0, 0]} isAnimationActive={!reduced} animationDuration={300} shape={(props: unknown) => {
            const { x, y, width, height, payload } = props as { x: number; y: number; width: number; height: number; payload: { positive: boolean } };
            return <rect x={x} y={y} width={width} height={height} rx={Math.min(3, width / 2)} fill={payload.positive ? "var(--good)" : "#566172"} />;
          }} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

type ScatterPoint = { x: number; y: number; label: string; detail: string };

/** Two groups: the highlighted one in blue, the rest in gray, with a parity line. */
export function ParityScatter({ primary, secondary, xLabel, yLabel, domain, primaryLabel, secondaryLabel, format = percent }: {
  primary: ScatterPoint[]; secondary?: ScatterPoint[]; xLabel: string; yLabel: string; domain: [number, number];
  primaryLabel: string; secondaryLabel?: string; format?: (v: number) => string;
}) {
  const reduced = useReducedMotion();
  const tip = ({ payload }: { payload?: readonly { payload?: ScatterPoint }[] }) => {
    const d = payload?.[0]?.payload;
    return d ? <Tip><div className="font-medium">{d.label}</div><div className="num text-ink-2">{d.detail}</div></Tip> : null;
  };
  return (
    <div>
      <div className="h-52">
        <ResponsiveContainer>
          <ScatterChart margin={{ top: 6, right: 8, left: -16, bottom: 4 }}>
            <CartesianGrid stroke="var(--grid)" />
            <XAxis type="number" dataKey="x" domain={domain} {...axis} tickFormatter={format} name={xLabel} />
            <YAxis type="number" dataKey="y" domain={domain} {...axis} tickFormatter={format} name={yLabel} />
            <ZAxis range={[50, 50]} />
            <ReferenceLine segment={[{ x: domain[0], y: domain[0] }, { x: domain[1], y: domain[1] }]} stroke="var(--ink-2)" strokeDasharray="4 3" ifOverflow="hidden" />
            <Tooltip content={tip} cursor={false} />
            {secondary && <Scatter data={secondary} fill="#566172" stroke="var(--surface)" strokeWidth={1.5} isAnimationActive={!reduced} animationDuration={300} />}
            <Scatter data={primary} fill="var(--series-1)" stroke="var(--surface)" strokeWidth={1.5} isAnimationActive={!reduced} animationDuration={300} />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-2">
        <span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-series-1" /> {primaryLabel}</span>
        {secondaryLabel && <span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-[#566172]" /> {secondaryLabel}</span>}
        <span className="ml-auto">x: {xLabel} · y: {yLabel} · dashed: equal</span>
      </div>
    </div>
  );
}

export function TrendLine({ data, dataKey, label, reference, height = 200, domain }: {
  data: Record<string, unknown>[]; dataKey: string; label: string; reference?: { y: number; label: string }; height?: number; domain?: [number, number];
}) {
  const reduced = useReducedMotion();
  return (
    <div style={{ height }}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey="date" {...axis} tickFormatter={(d: string) => d.slice(5)} interval="preserveStartEnd" minTickGap={24} />
          <YAxis {...axis} domain={domain ?? ["auto", "auto"]} />
          <Tooltip content={({ payload }) => {
            const d = payload?.[0]?.payload as { date?: string; opp?: string } & Record<string, unknown> | undefined;
            return d ? <Tip>{d.date}{d.opp ? ` vs ${d.opp}` : ""}<div>{label}: <span className="num">{Number(d[dataKey]).toFixed(Number.isInteger(d[dataKey]) ? 0 : 1)}</span></div></Tip> : null;
          }} />
          {reference && <ReferenceLine y={reference.y} stroke="var(--ink-2)" strokeDasharray="4 3" label={{ value: reference.label, fill: "var(--ink-2)", fontSize: 11, position: "insideTopRight" }} />}
          <Line dataKey={dataKey} stroke="var(--series-1)" strokeWidth={2} dot={{ r: 2.5, fill: "var(--series-1)", strokeWidth: 0 }} activeDot={{ r: 5, stroke: "var(--surface)", strokeWidth: 2 }} isAnimationActive={!reduced} animationDuration={300} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
