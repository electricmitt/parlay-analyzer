"use client";
import clsx from "clsx";
import { Activity, BrainCircuit, Layers, PanelLeftClose, PanelLeftOpen, Radar, Settings, TrendingUp, UserSearch, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { StatusDot } from "@/components/ui";
import { useApi } from "@/lib/api";
import { useSlate } from "@/lib/slate";
import { engineStatus } from "@/lib/status";
import type { Health, Slate } from "@/lib/types";

const NAV = [
  ["/", "Command Center", Radar],
  ["/players", "Player Research", UserSearch],
  ["/odds", "Odds Intelligence", Activity],
  ["/parlay", "Parlay Builder", Layers],
  ["/performance", "Performance", TrendingUp],
  ["/learning", "Learning Center", BrainCircuit],
  ["/settings", "Settings", Settings],
] as const;

const STATE_LABEL = { operational: "Operational", degraded: "Degraded", offline: "Offline" };

export function Sidebar({ collapsed, onToggle, mobileOpen, onCloseMobile }: {
  collapsed: boolean; onToggle: () => void; mobileOpen: boolean; onCloseMobile: () => void;
}) {
  const path = usePathname();
  const { date, isToday } = useSlate();
  const health = useApi<Health>("/api/health", { pollMs: 60_000 });
  const slate = useApi<Slate>(`/api/slate?date=${date}`);
  const { state, reasons } = engineStatus(health.data, health.error, slate.data?.totals.games ?? null, isToday);

  return (
    <>
      {mobileOpen && <div className="fixed inset-0 z-30 bg-black/60 lg:hidden" onClick={onCloseMobile} aria-hidden />}
      <aside
        className={clsx(
          "fixed inset-y-0 left-0 z-40 flex w-60 flex-col border-r border-line bg-page-2 transition-[width,transform] duration-200 ease-out lg:sticky lg:top-0 lg:h-screen lg:translate-x-0",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
          collapsed ? "lg:w-[60px]" : "lg:w-56",
        )}
      >
        <div className="flex h-14 items-center gap-2.5 px-4">
          <span className="relative flex size-6 shrink-0 items-center justify-center rounded-md border border-line bg-elevated" aria-hidden>
            <span className="size-2 rounded-full bg-gradient-to-br from-series-1 to-cyan" />
          </span>
          <span className={clsx("truncate text-sm font-medium tracking-tight", collapsed && "lg:hidden")}>Courtside AI</span>
          <button onClick={onCloseMobile} className="ml-auto text-ink-2 hover:text-ink lg:hidden" aria-label="Close menu"><X size={18} /></button>
        </div>

        <nav className="flex-1 space-y-0.5 px-2 py-2" aria-label="Main">
          {NAV.map(([href, label, Icon]) => {
            const active = href === "/" ? path === "/" || path.startsWith("/games") : path.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                onClick={onCloseMobile}
                title={collapsed ? label : undefined}
                aria-current={active ? "page" : undefined}
                className={clsx(
                  "flex h-9 items-center gap-3 rounded-lg px-2.5 text-sm transition-colors duration-150",
                  active ? "bg-series-1/12 text-ink shadow-[inset_2px_0_0_var(--series-1),0_0_18px_rgb(59_130_246/0.12)]" : "text-ink-2 hover:bg-elevated hover:text-ink",
                )}
              >
                <Icon size={17} strokeWidth={1.6} className={clsx("shrink-0", active && "text-[#7fb0fa]")} aria-hidden />
                <span className={clsx("truncate", collapsed && "lg:hidden")}>{label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="space-y-1 border-t border-line p-2">
          <div className="flex items-center gap-2.5 rounded-lg px-2.5 py-2" title={reasons.join(" ") || "All systems reporting normally."}>
            <StatusDot state={state} />
            <span className={clsx("min-w-0 text-xs", collapsed && "lg:hidden")}>
              <span className="block text-ink">AI system</span>
              <span className="block truncate text-ink-2">{STATE_LABEL[state]}</span>
            </span>
          </div>
          <button
            onClick={onToggle}
            className="hidden h-9 w-full items-center gap-3 rounded-lg px-2.5 text-xs text-ink-2 transition-colors duration-150 hover:bg-elevated hover:text-ink lg:flex"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? <PanelLeftOpen size={17} strokeWidth={1.6} className="shrink-0" /> : <PanelLeftClose size={17} strokeWidth={1.6} className="shrink-0" />}
            {!collapsed && "Collapse"}
          </button>
        </div>
      </aside>
    </>
  );
}
