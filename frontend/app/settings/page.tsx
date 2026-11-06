"use client";
import { useEffect, useState } from "react";
import { Button, Card, Empty, ErrorNote, inputCls, PageHeader, Skeleton } from "@/components/ui";
import { api, fmtTime, useApi } from "@/lib/api";

type Prefs = {
  preferred_book: string; bankroll_units: number; preferred_markets: string[]; max_parlay_legs: number;
  min_ev: number; risk_tolerance: string; alert_channels: string[]; teams_filter: string[];
};
type Note = { id: number; kind: string; title: string; body: string; created_at: string };

export default function Settings() {
  const { data, error } = useApi<Prefs>("/api/preferences");
  const notes = useApi<Note[]>("/api/notifications?limit=30");
  const [p, setP] = useState<Prefs | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => { if (data) setP(data); }, [data]);

  async function save() {
    try {
      await api("/api/preferences", { method: "PUT", body: JSON.stringify(p) });
      setMsg("Saved.");
    } catch (e) { setMsg((e as Error).message); }
  }
  const input = `${inputCls} mt-1 w-full`;
  return (
    <div className="max-w-3xl space-y-6">
      <PageHeader title="Settings">Preferences and the notification history.</PageHeader>
      <ErrorNote error={error} />
      {!p && !error && <Skeleton className="h-48" />}
      {p && (
        <Card title="Betting preferences">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm">Preferred sportsbook<br /><input className={input} value={p.preferred_book} onChange={(e) => setP({ ...p, preferred_book: e.target.value })} /></label>
            <label className="text-sm">Bankroll (units)<br /><input className={input} type="number" value={p.bankroll_units} onChange={(e) => setP({ ...p, bankroll_units: +e.target.value })} /></label>
            <label className="text-sm">Minimum EV (fraction, e.g. 0.03)<br /><input className={input} type="number" step="0.01" value={p.min_ev} onChange={(e) => setP({ ...p, min_ev: +e.target.value })} /></label>
            <label className="text-sm">Max parlay legs<br /><input className={input} type="number" min={2} max={5} value={p.max_parlay_legs} onChange={(e) => setP({ ...p, max_parlay_legs: +e.target.value })} /></label>
            <label className="text-sm">Preferred markets (comma separated)<br /><input className={input} value={p.preferred_markets.join(",")} onChange={(e) => setP({ ...p, preferred_markets: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} /></label>
            <label className="text-sm">Risk tolerance<br />
              <select className={input} value={p.risk_tolerance} onChange={(e) => setP({ ...p, risk_tolerance: e.target.value })}>
                <option>conservative</option><option>balanced</option><option>aggressive</option>
              </select>
            </label>
          </div>
          <div className="mt-3 flex items-center gap-3"><Button onClick={save}>Save</Button>{msg && <span className="text-sm text-ink-2">{msg}</span>}</div>
          <p className="mt-3 text-xs text-ink-2">
            Stored preferences are saved now. The server-side eligibility filters (MIN_EV, staking caps) are still set in
            <code> .env</code>; wiring these UI preferences into the filters is a Phase 2 item. Alert channels (Discord,
            Telegram) are configured with environment variables.
          </p>
        </Card>
      )}
      <Card title="Notifications">
        <ul className="space-y-2 text-sm">
          {notes.data?.map((n) => (
            <li key={n.id} className="border-b border-line pb-2">
              <div className="font-medium">{n.title}</div>
              <div className="text-ink-2">{n.body}</div>
              <div className="text-xs text-ink-2">{n.kind} · {fmtTime(n.created_at)}</div>
            </li>
          ))}
          {notes.data && !notes.data.length && <li><Empty title="No notifications yet." /></li>}
        </ul>
      </Card>
    </div>
  );
}
