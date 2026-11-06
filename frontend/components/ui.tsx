"use client";
import clsx from "clsx";
import { AlertTriangle, Check, CircleAlert, CircleX, Info, Inbox } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

export function Card({ title, action, children, className, eyebrow }: {
  title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; eyebrow?: ReactNode;
}) {
  return (
    <section className={clsx("rounded-xl border border-line bg-surface p-4", className)}>
      {(title || action || eyebrow) && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            {eyebrow && <div className="eyebrow mb-0.5">{eyebrow}</div>}
            {title && <h2 className="text-sm font-medium text-ink">{title}</h2>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function PageHeader({ title, children, action }: { title: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="max-w-3xl">
        <h1 className="text-xl font-medium tracking-tight text-ink">{title}</h1>
        {children && <div className="mt-1 text-sm leading-relaxed text-ink-2">{children}</div>}
      </div>
      {action}
    </div>
  );
}

export function Section({ title, hint, action, children }: { title: string; hint?: ReactNode; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="eyebrow">{title}</h2>
          {hint && <div className="mt-0.5 text-xs text-ink-2">{hint}</div>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3">
      <div className="text-xs text-ink-2">{label}</div>
      <div className="num mt-1 text-xl font-medium text-ink">{value}</div>
      {hint && <div className="mt-1 text-xs text-ink-2">{hint}</div>}
    </div>
  );
}

const STATUS = {
  good: { cls: "bg-good/12 text-good-text", Icon: Check },
  warning: { cls: "bg-warning/12 text-warning", Icon: CircleAlert },
  serious: { cls: "bg-serious/12 text-serious", Icon: AlertTriangle },
  critical: { cls: "bg-critical/12 text-critical", Icon: CircleX },
  neutral: { cls: "bg-neutral text-ink-2", Icon: null },
  info: { cls: "bg-series-1/15 text-[#93bbfb]", Icon: Info },
} as const;
export type Tone = keyof typeof STATUS;

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  const { cls, Icon } = STATUS[tone];
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium", cls)}>
      {Icon && <Icon size={12} aria-hidden />}
      {children}
    </span>
  );
}

export function Button({ children, onClick, disabled, variant = "primary", type = "button", title, className }: {
  children: ReactNode; onClick?: () => void; disabled?: boolean; variant?: "primary" | "ghost";
  type?: "button" | "submit"; title?: string; className?: string;
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={clsx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-45",
        variant === "primary"
          ? "bg-series-1 text-white hover:bg-[#5593f7] hover:shadow-[0_0_16px_rgb(59_130_246/0.3)] disabled:hover:bg-series-1 disabled:hover:shadow-none"
          : "border border-line text-ink hover:bg-elevated",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function Empty({ title, children, action, icon }: { title?: ReactNode; children?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-line px-6 py-8 text-center">
      <span className="text-muted" aria-hidden>{icon ?? <Inbox size={20} strokeWidth={1.5} />}</span>
      {title && <div className="text-sm font-medium text-ink">{title}</div>}
      {children && <div className="max-w-xl text-sm text-ink-2">{children}</div>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div role="alert" className="flex gap-2 rounded-lg border border-critical/30 bg-critical/8 p-3 text-sm text-ink">
      <CircleX size={16} className="mt-0.5 shrink-0 text-critical" aria-hidden />
      <div>
        {error}
        {error.includes("Failed to fetch") && (
          <div className="mt-1 text-xs text-ink-2">
            The API is not reachable. Start it with <code className="num">courtside serve --port 8000</code>.
          </div>
        )}
      </div>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("skeleton", className)} aria-hidden />;
}

export function Th({ children, right }: { children?: ReactNode; right?: boolean }) {
  return <th className={clsx("px-2 py-1.5 text-xs font-medium whitespace-nowrap text-ink-2", right ? "text-right" : "text-left")}>{children}</th>;
}
export function Td({ children, right, className }: { children?: ReactNode; right?: boolean; className?: string }) {
  return <td className={clsx("px-2 py-1.5 text-sm", right && "num text-right", className)}>{children}</td>;
}

export function resultBadge(r: string | null) {
  if (!r) return <Badge>open</Badge>;
  const tone = r === "win" ? "good" : r === "loss" ? "critical" : "neutral";
  return <Badge tone={tone}>{r}</Badge>;
}

export function Segmented<T extends string>({ value, onChange, options, label }: {
  value: T; onChange: (v: T) => void; options: readonly (readonly [T, string])[]; label: string;
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-lg border border-line bg-page-2 p-0.5">
      {options.map(([k, l]) => (
        <button
          key={k}
          type="button"
          aria-pressed={value === k}
          onClick={() => onChange(k)}
          className={clsx(
            "rounded-md px-2.5 py-1 text-xs font-medium whitespace-nowrap transition-colors duration-150",
            value === k ? "bg-elevated text-ink shadow-[inset_0_0_0_1px_var(--border)]" : "text-ink-2 hover:text-ink",
          )}
        >
          {l}
        </button>
      ))}
    </div>
  );
}

export const inputCls =
  "rounded-lg border border-line bg-page-2 px-2.5 py-1.5 text-sm text-ink placeholder:text-muted transition-colors duration-150 hover:border-[#343d4b] focus:border-series-1 focus:outline-none";

export function StatusDot({ state }: { state: "operational" | "degraded" | "offline" }) {
  const color = state === "operational" ? "text-good" : state === "degraded" ? "text-warning" : "text-critical";
  return <span className={clsx("pulse-dot inline-block size-2 shrink-0 rounded-full bg-current", color, state === "offline" && "animate-none")} aria-hidden />;
}

/** Counts up to a value when it changes, unless the user prefers reduced motion. */
export function AnimatedNumber({ value }: { value: number }) {
  const [shown, setShown] = useState(0);
  const from = useRef(0);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setShown(value);
      from.current = value;
      return;
    }
    const start = performance.now();
    const origin = from.current;
    let raf = 0;
    const tick = (t: number) => {
      const k = Math.min((t - start) / 300, 1);
      setShown(Math.round(origin + (value - origin) * (1 - (1 - k) ** 3)));
      if (k < 1) raf = requestAnimationFrame(tick);
      else from.current = value;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value]);
  return <>{shown.toLocaleString("en-US")}</>;
}

export function useReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => setReduced(window.matchMedia("(prefers-reduced-motion: reduce)").matches), []);
  return reduced;
}
