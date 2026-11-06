"use client";
import { useCallback, useEffect, useRef, useState } from "react";

export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const REFRESH_EVENT = "courtside:refresh";

export async function api<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const j = await r.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {}
    // 4xx details are written for the user; anything else keeps its status code for diagnosis.
    throw new Error(r.status >= 400 && r.status < 500 ? detail : `${r.status}: ${detail}`);
  }
  return r.json() as Promise<T>;
}

/** Tell every mounted useApi to reload, e.g. after an analysis run. */
export const refreshAll = () => window.dispatchEvent(new Event(REFRESH_EVENT));

export function useApi<T>(path: string | null, opts?: { pollMs?: number }) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const latest = useRef(path);
  latest.current = path;

  const load = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try {
      const res = await api<T>(path);
      if (latest.current === path) {
        setData(res);
        setError(null);
      }
    } catch (e) {
      if (latest.current === path) setError((e as Error).message);
    } finally {
      if (latest.current === path) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    setData(null); // another date's numbers must never show under this date's heading
    setError(null);
    load();
  }, [load]);

  useEffect(() => {
    window.addEventListener(REFRESH_EVENT, load);
    const timer = opts?.pollMs ? setInterval(load, opts.pollMs) : undefined;
    return () => {
      window.removeEventListener(REFRESH_EVENT, load);
      if (timer) clearInterval(timer);
    };
  }, [load, opts?.pollMs]);

  return { data, error, loading, reload: load };
}

export const pct = (x: number | null | undefined, d = 0) =>
  x == null ? "—" : `${(x * 100).toFixed(d)}%`;
export const signedPct = (x: number | null | undefined, d = 1) =>
  x == null ? "—" : `${x >= 0 ? "+" : ""}${(x * 100).toFixed(d)}%`;
export const odds = (a: number | null | undefined) => (a == null ? "—" : a > 0 ? `+${a}` : `${a}`);
export const num = (x: number | null | undefined, d = 1) => (x == null ? "—" : x.toFixed(d));
export const fmtTime = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleString("en-US", {
        timeZone: "America/New_York",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      }) + " ET"
    : "—";
export const fmtClock = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" }) + " ET"
    : "—";
export const minutesSince = (iso: string | null | undefined) =>
  iso ? (Date.now() - new Date(iso).getTime()) / 60000 : null;
export function ago(iso: string | null | undefined) {
  const m = minutesSince(iso);
  if (m == null) return "never";
  if (m < 1) return "just now";
  if (m < 60) return `${Math.round(m)} min ago`;
  if (m < 48 * 60) return `${Math.round(m / 60)} hr ago`;
  return `${Math.round(m / 1440)} days ago`;
}
export const todayET = () =>
  new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
export const shiftDate = (d: string, days: number) => {
  const t = new Date(`${d}T12:00:00Z`);
  t.setUTCDate(t.getUTCDate() + days);
  return t.toISOString().slice(0, 10);
};
export const longDate = (d: string) =>
  new Date(`${d}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", weekday: "short", month: "short", day: "numeric" });

const BOOKS: Record<string, string> = {
  hardrockbet: "Hard Rock", hardrockbet_fl: "Hard Rock", draftkings: "DraftKings", fanduel: "FanDuel",
  betmgm: "BetMGM", williamhill_us: "Caesars", espnbet: "ESPN BET", fanatics: "Fanatics", other: "Other",
};
export const bookName = (b: string) => BOOKS[b] ?? b;
