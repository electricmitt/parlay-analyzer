"use client";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { AnimatedNumber, Skeleton } from "@/components/ui";

export function MetricCard({ label, value, Icon, context, freshness }: {
  label: string; value: number | null; Icon: LucideIcon; context?: ReactNode; freshness?: ReactNode;
}) {
  return (
    <div className="lift rounded-xl border border-line bg-surface px-4 py-3">
      <div className="flex items-center justify-between text-ink-2">
        <span className="text-xs">{label}</span>
        <Icon size={14} strokeWidth={1.6} aria-hidden />
      </div>
      <div className="num mt-1.5 text-3xl font-medium tracking-tight text-ink">
        {value == null ? <Skeleton className="h-9 w-14" /> : <AnimatedNumber value={value} />}
      </div>
      <div className="mt-1 min-h-4 text-xs text-ink-2">{context}</div>
      <div className="mt-0.5 min-h-4 text-xs text-ink-2">{freshness}</div>
    </div>
  );
}
