"use client";
import Link from "next/link";
import { Fragment, useState } from "react";
import { bookName, fmtTime, num, odds, pct, signedPct } from "@/lib/api";
import type { Pred } from "@/lib/types";
import { Badge, resultBadge, Td, Th } from "./ui";

export function PropTable({ preds, showGame = true }: { preds: Pred[]; showGame?: boolean }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[900px]">
        <thead className="border-b border-line">
          <tr>
            {showGame && <Th>Game</Th>}
            <Th>Player</Th>
            <Th>Market</Th>
            <Th>Book</Th>
            <Th right>Price</Th>
            <Th right>Proj (80% PI)</Th>
            <Th right>Model P</Th>
            <Th right>Market P</Th>
            <Th right>Fair</Th>
            <Th right>EV</Th>
            <Th>Decision</Th>
          </tr>
        </thead>
        <tbody>
          {preds.map((p) => (
            <Fragment key={p.id}>
              <tr
                className="cursor-pointer border-b border-line transition-colors duration-150 hover:bg-elevated"
                onClick={() => setOpen(open === p.id ? null : p.id)}
              >
                {showGame && (
                  <Td>
                    <Link href={`/games/${p.game_id}`} className="text-[#7fb0fa] hover:underline" onClick={(e) => e.stopPropagation()}>
                      {p.game}
                    </Link>
                  </Td>
                )}
                <Td>
                  <Link href={`/players/${p.player_id}`} className="font-medium hover:underline" onClick={(e) => e.stopPropagation()}>
                    {p.player}
                  </Link>
                </Td>
                <Td>
                  {p.side.toUpperCase()} {p.line} {p.market_label}
                </Td>
                <Td>{bookName(p.book)}</Td>
                <Td right>{odds(p.price)}</Td>
                <Td right>
                  {num(p.proj_mean)} <span className="text-muted">({num(p.proj_p10, 0)}–{num(p.proj_p90, 0)})</span>
                </Td>
                <Td right>{pct(p.model_prob)}</Td>
                <Td right>{pct(p.consensus_prob ?? p.novig_prob)}</Td>
                <Td right>{odds(p.fair_odds)}</Td>
                <Td right className={p.ev > 0 ? "text-good-text" : p.ev < 0 ? "text-critical" : "text-ink-2"}>{signedPct(p.ev)}</Td>
                <Td>
                  {p.result ? resultBadge(p.result) : p.status === "withdrawn" ? <Badge tone="serious">withdrawn</Badge>
                    : p.published ? <Badge tone="good">PICK</Badge> : <Badge>PASS</Badge>}
                </Td>
              </tr>
              {open === p.id && (
                <tr className="border-b border-line bg-page-2">
                  <td colSpan={showGame ? 11 : 10} className="p-3 text-sm">
                    <PropDetail p={p} />
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PropDetail({ p }: { p: Pred }) {
  return (
    <div className="grid gap-4 [&>*]:min-w-0 md:grid-cols-[repeat(auto-fit,minmax(200px,1fr))]">
      <div>
        <div className="mb-1 eyebrow">SUPPORTING FACTORS</div>
        <ul className="list-disc space-y-0.5 pl-4">{p.factors.map((f, i) => <li key={i}>{f}</li>)}</ul>
      </div>
      <div>
        <div className="mb-1 eyebrow">RISKS / WHAT COULD INVALIDATE IT</div>
        <ul className="list-disc space-y-0.5 pl-4">{p.risks.map((f, i) => <li key={i}>{f}</li>)}</ul>
        {p.reasons.length > 0 && (
          <>
            <div className="mb-1 mt-3 eyebrow">WHY NOT ELIGIBLE</div>
            <ul className="list-disc space-y-0.5 pl-4">{p.reasons.map((f, i) => <li key={i}>{f}</li>)}</ul>
          </>
        )}
      </div>
      <div className="space-y-1 text-xs text-ink-2">
        <div>Projected minutes: <b className="text-ink">{num(p.proj_minutes)}</b> · median {num(p.proj_p50, 0)}</div>
        <div>Book implied (with vig): {pct(p.implied_prob, 1)} · no-vig same book: {pct(p.novig_prob, 1)}</div>
        <div>Analysis stake (¼-Kelly, capped): {p.kelly_stake_units ? `${p.kelly_stake_units}u` : "—"}</div>
        <div>Risk level (interval width): {p.risk_level}</div>
        <div>Odds as of {fmtTime(p.odds_fetched_at)} · generated {fmtTime(p.created_at)}</div>
        <div>Record type: {p.record_type} · status: {p.status}</div>
        {p.actual != null && <div>Actual: <b className="text-ink">{p.actual}</b> in {num(p.actual_minutes, 0)} min · tags: {p.error_tags?.join(", ")}</div>}
        <div className="pt-1">Data: {Object.entries(p.data_quality).map(([k, v]) => `${k}=${String(v)}`).join(" · ")}</div>
      </div>
    </div>
  );
}
