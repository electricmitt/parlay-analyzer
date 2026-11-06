"use client";
import Link from "next/link";
import { use, useState } from "react";
import { TeamLogo } from "@/components/media";
import { PropTable } from "@/components/PropTable";
import { Badge, Card, Empty, ErrorNote, inputCls, Skeleton, Stat, Td, Th } from "@/components/ui";
import { fmtTime, num, useApi } from "@/lib/api";
import type { Game, Pred } from "@/lib/types";

type Form = { games: number; pace?: number; off_rating?: number; def_rating?: number; pts?: number; opp_pts?: number };
type Proj = {
  player_id: string; player: string; team_id: string; position: string | null; minutes: number; sd_minutes: number;
  injury_status: string | null; n_games: number; markets: Record<string, { mean: number; p10: number; p50: number; p90: number }>;
};
type Detail = {
  game: Game; team_form: { home: Form; away: Form };
  environment: { projected_possessions: number; projected_home: number; projected_away: number; method: string } | null;
  projections: Proj[]; injuries: { player_id: string; player: string; team_id: string; status: string; detail: string | null }[];
  props: Pred[]; box_score: { player: string; team_id: string; minutes: number; pts: number; reb: number; ast: number; fg3m: number; dnp: boolean }[];
};

const MKTS = [["pts", "PTS"], ["reb", "REB"], ["ast", "AST"], ["fg3m", "3PM"], ["pra", "PRA"]] as const;

export default function GamePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, error } = useApi<Detail>(`/api/games/${id}`);
  const [team, setTeam] = useState<"both" | "home" | "away">("both");
  if (error) return <ErrorNote error={error} />;
  if (!data) return <div className="space-y-3"><Skeleton className="h-16" /><Skeleton className="h-64" /></div>;
  const g = data.game;
  const projs = data.projections.filter((p) => team === "both" || p.team_id === (team === "home" ? g.home.id : g.away.id));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex flex-wrap items-center gap-2 text-xl font-medium tracking-tight"><TeamLogo abbr={g.away.abbr} size={30} /> {g.away.name} @ {g.home.name} <TeamLogo abbr={g.home.abbr} size={30} /></h1>
        <p className="text-sm text-ink-2">{fmtTime(g.start_time)} · {g.status.replace("STATUS_", "").toLowerCase()}
          {g.home.score != null && ` · ${g.away.abbr} ${g.away.score} – ${g.home.abbr} ${g.home.score}`}</p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Projected possessions" value={num(data.environment?.projected_possessions)} />
        <Stat label="Projected score" value={data.environment ? `${num(data.environment.projected_away, 0)} – ${num(data.environment.projected_home, 0)}` : "—"}
              hint={data.environment ? `${g.away.abbr} – ${g.home.abbr}` : undefined} />
        <Stat label={`${g.away.abbr} pace / ORtg / DRtg`} value={<span className="text-base">{num(data.team_form.away.pace)} / {num(data.team_form.away.off_rating)} / {num(data.team_form.away.def_rating)}</span>} hint={`last ${data.team_form.away.games} games`} />
        <Stat label={`${g.home.abbr} pace / ORtg / DRtg`} value={<span className="text-base">{num(data.team_form.home.pace)} / {num(data.team_form.home.off_rating)} / {num(data.team_form.home.def_rating)}</span>} hint={`last ${data.team_form.home.games} games`} />
      </div>
      {data.environment && <p className="text-xs text-ink-2">Game environment method: {data.environment.method}. A simple descriptive estimate — not used to price props directly.</p>}

      <Card title="Player projections (median and 80% interval)" action={
        <select value={team} onChange={(e) => setTeam(e.target.value as typeof team)} className={`${inputCls} h-7 py-0 text-xs`}>
          <option value="both">Both teams</option><option value="away">{g.away.abbr}</option><option value="home">{g.home.abbr}</option>
        </select>}>
        {projs.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[800px]">
              <thead className="border-b border-line"><tr><Th>Player</Th><Th>Status</Th><Th right>Min</Th>{MKTS.map(([, l]) => <Th key={l} right>{l}</Th>)}</tr></thead>
              <tbody>
                {projs.map((p) => (
                  <tr key={p.player_id} className="border-b border-line">
                    <Td><Link href={`/players/${p.player_id}`} className="font-medium hover:underline">{p.player}</Link> <span className="text-xs text-ink-2">{p.position}</span></Td>
                    <Td>{p.injury_status ? <Badge tone="warning">{p.injury_status}</Badge> : <span className="text-xs text-ink-2">not listed</span>}</Td>
                    <Td right>{num(p.minutes)} <span className="text-muted">±{num(p.sd_minutes, 0)}</span></Td>
                    {MKTS.map(([k]) => (
                      <Td key={k} right>{num(p.markets[k]?.p50, 0)} <span className="text-xs text-ink-2">({num(p.markets[k]?.p10, 0)}–{num(p.markets[k]?.p90, 0)})</span></Td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty title="Your intelligence report is ready to generate.">Run analysis on this date. Only upcoming games are projected.</Empty>}
      </Card>

      <Card title="Prop lines evaluated">
        {data.props.length ? <PropTable preds={data.props} showGame={false} /> : <Empty title="No odds recorded for this game." />}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Injury report">
          {data.injuries.length ? (
            <ul className="space-y-1 text-sm">{data.injuries.map((i) => (
              <li key={i.player_id}><Badge tone={i.status === "Out" ? "critical" : "warning"}>{i.status}</Badge> {i.player} <span className="text-ink-2">{i.detail}</span></li>
            ))}</ul>
          ) : <Empty>No injuries listed for either team.</Empty>}
        </Card>
        <Card title="Box score">
          {data.box_score.length ? (
            <table className="w-full"><thead className="border-b border-line"><tr><Th>Player</Th><Th right>MIN</Th><Th right>PTS</Th><Th right>REB</Th><Th right>AST</Th><Th right>3PM</Th></tr></thead>
              <tbody>{data.box_score.filter((b) => !b.dnp).map((b) => (
                <tr key={b.player} className="border-b border-line"><Td>{b.player}</Td><Td right>{b.minutes}</Td><Td right>{b.pts}</Td><Td right>{b.reb}</Td><Td right>{b.ast}</Td><Td right>{b.fg3m}</Td></tr>
              ))}</tbody></table>
          ) : <Empty>Available after the game is final.</Empty>}
        </Card>
      </div>
    </div>
  );
}
