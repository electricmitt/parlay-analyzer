import { api, bookName, odds, pct, signedPct } from "./api";
import { playerInsights, played } from "./insights";
import type { PlayerDetail, PlayerHit, Pred, Prefs, Recs } from "./types";

export type AnswerBlock =
  | { kind: "text"; text: string }
  | { kind: "props"; items: Pred[]; note?: (p: Pred) => string }
  | { kind: "stats"; rows: [string, string][] }
  | { kind: "list"; title?: string; items: string[] }
  | { kind: "link"; href: string; label: string };
export type Answer = { blocks: AnswerBlock[]; source: string };

export const SUGGESTIONS = [
  "What are tonight's strongest positive EV opportunities?",
  "Show me the safest qualifying props based on my filters",
  "Which available lines differ most from the model's projections?",
  "Why does the model favor the top pick?",
];

const STOP = new Set(("analyze analyse show tell me about recent scoring trend trends trends? stats form how has have is are the a an of for "
  + "what whats why does do did model favor favour favors selection this that on in with his her their tonight today player points rebounds "
  + "assists threes last games game pick picks prop props line lines over under and or to it s please").split(/\s+/));

const uncertainty = (p: Pred) => (p.proj_p90 - p.proj_p10) / Math.max(p.line, 1);
/** The same bet is priced at several books; keep only the best price for each. */
const bestPerProp = (props: Pred[]) => {
  const best = new Map<string, Pred>();
  for (const p of props) {
    const k = `${p.player_id}|${p.market}|${p.side}|${p.line}`;
    const cur = best.get(k);
    if (!cur || p.ev > cur.ev) best.set(k, p);
  }
  return [...best.values()];
};
const legName = (p: Pred) => `${p.player} ${p.side.toUpperCase()} ${p.line} ${p.market_label}`;

async function findPlayer(q: string): Promise<PlayerHit | PlayerHit[] | null> {
  const words = q.toLowerCase().replace(/['’]s\b/g, "").replace(/[^a-z\s'-]/g, " ").split(/\s+/).filter((w) => w.length >= 3 && !STOP.has(w));
  if (!words.length) return null;
  const hits = await api<PlayerHit[]>(`/api/players?q=${encodeURIComponent(words.join(" "))}`);
  if (hits.length === 1) return hits[0];
  if (hits.length > 1) return hits;
  for (const w of [...words].sort((a, b) => b.length - a.length)) {
    const r = await api<PlayerHit[]>(`/api/players?q=${encodeURIComponent(w)}`);
    if (r.length === 1) return r[0];
    if (r.length > 1) return r;
  }
  return null;
}

function explain(p: Pred): AnswerBlock[] {
  return [
    { kind: "text", text: `${legName(p)} at ${bookName(p.book)} ${odds(p.price)}: model ${pct(p.model_prob, 1)} vs ${pct(p.implied_prob, 1)} implied by the price, EV ${signedPct(p.ev)}. Status: ${p.published ? "published pick" : p.eligible ? "eligible" : "not eligible"}.` },
    { kind: "list", title: "Supporting factors", items: p.factors },
    { kind: "list", title: "Risks", items: p.risks },
    ...(p.reasons.length ? [{ kind: "list" as const, title: "Why it did not qualify", items: p.reasons }] : []),
  ];
}

/** Answers come only from the app's own API. There is no language model, so nothing can be invented. */
export async function answer(question: string, date: string): Promise<Answer> {
  const q = question.toLowerCase();
  const source = `Courtside data for ${date}`;

  if (/\b(differ|difference|gap|diverge|disagree|discrepan)/.test(q)) {
    const props = await api<Pred[]>(`/api/props?date=${date}`);
    if (!props.length) return { source, blocks: [{ kind: "text", text: "No odds have been evaluated for this slate, so there are no lines to compare." }] };
    const top = bestPerProp(props).sort((a, b) => Math.abs(b.proj_mean - b.line) - Math.abs(a.proj_mean - a.line)).slice(0, 5);
    return { source, blocks: [
      { kind: "text", text: "Largest gaps between the posted line and the model's projected mean. A big gap is often a sign of news the model lacks, not an edge." },
      { kind: "props", items: top, note: (p) => `proj ${p.proj_mean.toFixed(1)} vs line ${p.line}` },
    ] };
  }

  if (/\b(safest|safe|lowest risk|least risk|conservative|lowest uncertainty)\b/.test(q)) {
    const [props, prefs] = await Promise.all([api<Pred[]>(`/api/props?date=${date}&eligible_only=true`), api<Prefs>("/api/preferences")]);
    const filtered = props.filter((p) => p.ev >= prefs.min_ev && (!prefs.preferred_markets.length || prefs.preferred_markets.includes(p.market)));
    if (!filtered.length) return { source, blocks: [{ kind: "text", text: `No qualifying props match your saved filters (minimum EV ${pct(prefs.min_ev)}, markets: ${prefs.preferred_markets.join(", ") || "any"}). ${props.length} props qualified before those filters.` }] };
    const top = bestPerProp(filtered).sort((a, b) => uncertainty(a) - uncertainty(b) || b.model_prob - a.model_prob).slice(0, 5);
    return { source, blocks: [
      { kind: "text", text: `Narrowest projected ranges among qualifying props, using your filters (minimum EV ${pct(prefs.min_ev)}, markets: ${prefs.preferred_markets.join(", ") || "any"}). "Safest" here means least modelled uncertainty; any of these can lose.` },
      { kind: "props", items: top, note: (p) => `model ${pct(p.model_prob)} · ${p.risk_level} uncertainty` },
    ] };
  }

  if (/\b(why|reason|explain)\b/.test(q)) {
    const props = await api<Pred[]>(`/api/props?date=${date}`);
    if (!props.length) return { source, blocks: [{ kind: "text", text: "No props have been evaluated for this slate, so there is no selection to explain." }] };
    const who = await findPlayer(question);
    if (who && !Array.isArray(who)) {
      const mine = props.filter((p) => p.player_id === who.id);
      if (!mine.length) return { source, blocks: [{ kind: "text", text: `${who.name} has no evaluated prop on this slate.` }] };
      return { source, blocks: explain(mine[0]) };
    }
    const top = props.find((p) => p.published) ?? props.find((p) => p.eligible);
    if (!top) return { source, blocks: [{ kind: "text", text: `Nothing qualified on this slate. All ${props.length} evaluated props failed at least one filter, so the model favors no selection.` }] };
    return { source, blocks: explain(top) };
  }

  if (/\b(ev|edge|strongest|best|top|value|opportunit|recommend)/.test(q)) {
    const recs = await api<Recs>(`/api/recommendations?date=${date}`);
    if (recs.picks.length) return { source, blocks: [
      { kind: "text", text: `${recs.picks.length} published ${recs.picks.length === 1 ? "pick" : "picks"}, highest EV first. EV is an estimate at the listed price.` },
      { kind: "props", items: recs.picks.slice(0, 6), note: (p) => `EV ${signedPct(p.ev)} · model ${pct(p.model_prob)}` },
    ] };
    const props = await api<Pred[]>(`/api/props?date=${date}`);
    const raw = props.filter((p) => p.ev > 0).length;
    return { source, blocks: [{ kind: "text", text: props.length
      ? `No qualifying opportunities on this slate. ${raw} of ${props.length} evaluated props show positive raw EV, but none passed every filter.`
      : "No odds have been evaluated for this slate yet, so EV cannot be calculated." }] };
  }

  const who = await findPlayer(question);
  if (Array.isArray(who)) return { source: "Courtside player index", blocks: [
    { kind: "text", text: "More than one player matches. Which did you mean?" },
    { kind: "list", items: who.slice(0, 6).map((p) => `${p.name} (${p.team ?? "no team"})`) },
  ] };
  if (who) {
    const d = await api<PlayerDetail>(`/api/players/${who.id}`);
    const rows = played(d.game_log);
    const avg = (n: number, k: "pts" | "reb" | "ast" | "minutes") => {
      const s = rows.slice(0, n);
      return s.length ? (s.reduce((a, r) => a + r[k], 0) / s.length).toFixed(1) : "—";
    };
    return { source: `Game log through ${rows[0]?.date ?? "no games"}`, blocks: [
      { kind: "text", text: `${d.player.name}, ${d.player.team ?? "no team"} ${d.player.position ?? ""}${d.injury ? ` · ${d.injury.status}${d.injury.detail ? `: ${d.injury.detail}` : ""}` : ""}` },
      { kind: "stats", rows: [["Points L5 / L10 / L20", `${avg(5, "pts")} / ${avg(10, "pts")} / ${avg(20, "pts")}`], ["Rebounds L5 / L10", `${avg(5, "reb")} / ${avg(10, "reb")}`], ["Assists L5 / L10", `${avg(5, "ast")} / ${avg(10, "ast")}`], ["Minutes L5 / L10", `${avg(5, "minutes")} / ${avg(10, "minutes")}`]] },
      { kind: "list", title: "From the game log", items: playerInsights(d) },
      { kind: "link", href: `/players/${who.id}`, label: `Open ${d.player.name}` },
    ] };
  }

  return { source: "Courtside Intelligence", blocks: [
    { kind: "text", text: "I can't answer that from the app's data. I can show positive EV opportunities, the props with the least modelled uncertainty, the largest gaps between lines and projections, why the model rates a prop the way it does, or any player's recent trends." },
  ] };
}
