"use client";
import { useState } from "react";
import { Badge, Button, Card, Empty, ErrorNote, PageHeader, Td, Th } from "@/components/ui";
import { api, fmtTime, num, useApi } from "@/lib/api";

type Model = {
  id: number; name: string; version: string; status: string; trained_through: string | null; created_at: string;
  promoted_at: string | null; notes: string | null; dispersion: Record<string, number> | null;
  metrics: { gate?: { pass: boolean; reasons: string[]; type: string }; markets?: Record<string, { brier_model: number; brier_naive: number; ece_model: number; n: number }> };
};
type ErrSum = { tag_counts: Record<string, number>; n: number; mean_error: number | null; mae: number | null };
type Learning = { errors_overall: ErrSum; errors_by_market: Record<string, ErrSum>; models: Model[] };
type Run = { id: number; type: string; date: string; status: string; started_at: string; error: string | null };

export default function LearningCenter() {
  const { data, error, reload } = useApi<Learning>("/api/learning");
  const runs = useApi<Run[]>("/api/runs?limit=15");
  const [msg, setMsg] = useState<string | null>(null);

  async function act(path: string, body?: object) {
    setMsg(null);
    try {
      await api(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
      setMsg("Done.");
      reload();
    } catch (e) { setMsg((e as Error).message); }
  }
  const prodExists = data?.models.some((m) => m.status === "production");

  return (
    <div className="space-y-6">
      <PageHeader title="Learning Center">
          Models are only promoted after beating the incumbent (or the naive baseline, for the first model) on unseen
          walk-forward data with a significant paired-bootstrap improvement. Challengers also need shadow testing
          before promotion. Weekly evaluation registers candidates; it never auto-promotes.
        </PageHeader>
      <ErrorNote error={error} />
      {msg && <div className="rounded-lg border border-line bg-surface p-3 text-sm">{msg}</div>}

      <Card title="Model versions">
        {data?.models.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px]">
              <thead className="border-b border-line"><tr><Th>Version</Th><Th>Status</Th><Th>Trained through</Th><Th>Validation gate</Th><Th right>PTS Brier (model / naive)</Th><Th right>PTS ECE</Th><Th /></tr></thead>
              <tbody>
                {data.models.map((m) => {
                  const pts = m.metrics.markets?.pts;
                  return (
                    <tr key={m.id} className="border-b border-line align-top">
                      <Td><div className="num font-medium">{m.name} {m.version}</div><div className="text-xs text-ink-2">created {fmtTime(m.created_at)}</div></Td>
                      <Td><Badge tone={m.status === "production" ? "good" : m.status === "candidate" ? "info" : "neutral"}>{m.status}</Badge></Td>
                      <Td>{m.trained_through}</Td>
                      <Td>
                        {m.metrics.gate ? (m.metrics.gate.pass ? <Badge tone="good">passed</Badge> : (
                          <div><Badge tone="serious">failed</Badge><ul className="mt-1 list-disc pl-4 text-xs text-ink-2">{m.metrics.gate.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul></div>
                        )) : "—"}
                      </Td>
                      <Td right>{pts ? `${num(pts.brier_model, 4)} / ${num(pts.brier_naive, 4)}` : "—"}</Td>
                      <Td right>{pts ? num(pts.ece_model, 3) : "—"}</Td>
                      <Td>
                        {m.status !== "production" && (
                          <div className="flex gap-2">
                            {m.metrics.gate?.pass && !prodExists && <Button onClick={() => act(`/api/models/${m.id}/promote`, {})}>Promote</Button>}
                            {m.metrics.gate?.pass && prodExists && <Button onClick={() => act(`/api/models/${m.id}/promote`, { confirm_shadow_tested: true })}>Promote (shadow-tested)</Button>}
                            {m.status === "retired" && <Button variant="ghost" onClick={() => act(`/api/models/${m.id}/rollback`)}>Roll back to this</Button>}
                          </div>
                        )}
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : <Empty>No models registered. Run <code>courtside train</code>.</Empty>}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Detected error sources (settled live predictions)">
          {data && data.errors_overall.n ? (
            <>
              <p className="mb-2 text-sm text-ink-2">n={data.errors_overall.n} · mean error {num(data.errors_overall.mean_error, 2)} · MAE {num(data.errors_overall.mae, 2)}</p>
              <table className="w-full"><tbody>
                {Object.entries(data.errors_overall.tag_counts).sort((a, b) => b[1] - a[1]).map(([t, c]) => (
                  <tr key={t} className="border-b border-line"><Td>{t.replaceAll("_", " ")}</Td><Td right>{c}</Td></tr>
                ))}
              </tbody></table>
              <p className="mt-2 text-xs text-ink-2">Tags are heuristic and descriptive: minutes miss (&gt;25% off), blowout (margin ≥20), foul trouble (≥5 PF), shooting variance, tail outcome.</p>
            </>
          ) : <Empty>No settled live predictions yet.</Empty>}
        </Card>
        <Card title="Recent orchestrator runs">
          <table className="w-full"><thead className="border-b border-line"><tr><Th>#</Th><Th>Type</Th><Th>Date</Th><Th>Status</Th><Th>Started</Th></tr></thead>
            <tbody>{runs.data?.map((r) => (
              <tr key={r.id} className="border-b border-line" title={r.error ?? ""}>
                <Td>{r.id}</Td><Td>{r.type}</Td><Td>{r.date}</Td>
                <Td><Badge tone={r.status === "ok" ? "good" : r.status === "error" ? "critical" : "neutral"}>{r.status}</Badge></Td><Td>{fmtTime(r.started_at)}</Td>
              </tr>
            ))}</tbody></table>
        </Card>
      </div>
    </div>
  );
}
