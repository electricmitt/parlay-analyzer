"use client";
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { todayET } from "./api";

type Ctx = { date: string; setDate: (d: string) => void; isToday: boolean };
const SlateContext = createContext<Ctx | null>(null);

/** The slate date shared by the top bar and every page. It follows today until the user picks a date. */
export function SlateProvider({ children }: { children: ReactNode }) {
  const [date, setDateState] = useState(todayET);
  const pinned = useRef(false);

  // A link can open a specific slate: /?date=2026-11-04
  useEffect(() => {
    const d = new URLSearchParams(window.location.search).get("date");
    if (d && /^\d{4}-\d{2}-\d{2}$/.test(d)) {
      pinned.current = d !== todayET();
      setDateState(d);
    }
  }, []);

  useEffect(() => {
    const t = setInterval(() => {
      if (!pinned.current) setDateState(todayET());
    }, 60_000);
    return () => clearInterval(t);
  }, []);

  const value = useMemo(() => ({
    date,
    isToday: date === todayET(),
    setDate: (d: string) => {
      pinned.current = d !== todayET();
      setDateState(d);
    },
  }), [date]);
  return <SlateContext.Provider value={value}>{children}</SlateContext.Provider>;
}

export function useSlate() {
  const c = useContext(SlateContext);
  if (!c) throw new Error("useSlate must be used inside SlateProvider");
  return c;
}
