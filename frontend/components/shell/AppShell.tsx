"use client";
import { useEffect, useState, type ReactNode } from "react";
import { Assistant } from "./Assistant";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

export function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => setCollapsed(localStorage.getItem("courtside:sidebar") === "collapsed"), []);
  const toggle = () => {
    setCollapsed((c) => {
      localStorage.setItem("courtside:sidebar", c ? "open" : "collapsed");
      return !c;
    });
  };

  return (
    <div className="flex min-h-screen">
      <Sidebar collapsed={collapsed} onToggle={toggle} mobileOpen={mobileOpen} onCloseMobile={() => setMobileOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onOpenMenu={() => setMobileOpen(true)} />
        <main className="mx-auto w-full max-w-[1500px] flex-1 px-4 py-5 lg:px-6">{children}</main>
        <footer className="mx-auto w-full max-w-[1500px] px-4 pb-20 text-xs leading-relaxed text-ink-2 lg:px-6">
          Research tool only. Probabilities are model estimates with real uncertainty; no outcome is guaranteed and no
          wagers are placed. Bet only what you can afford to lose. If gambling stops being fun, call 1-800-GAMBLER.
        </footer>
      </div>
      <Assistant />
    </div>
  );
}
