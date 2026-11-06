export type Team = { id: string; abbr: string; name: string; score: number | null };
export type InjuryChip = { player_id: string; player: string; status: string };
export type Game = {
  id: string; date: string; start_time: string; status: string; home: Team; away: Team; started: boolean;
  props_evaluated?: number; eligible?: number; published?: number; decision?: string;
  home_record?: string | null; away_record?: string | null;
  injuries?: { home: InjuryChip[]; away: InjuryChip[] };
};
export type Slate = {
  date: string; games: Game[]; schedule_loaded: boolean;
  totals: { games: number; props_evaluated: number; eligible: number; published: number };
};
export type Pred = {
  id: number; game_id: string; player_id: string; player: string; market: string; market_label: string;
  side: string; line: number; book: string; price: number; model_prob: number; implied_prob: number;
  novig_prob: number | null; consensus_prob: number | null; fair_odds: number; ev: number;
  kelly_stake_units: number; proj_mean: number; proj_p10: number; proj_p50: number; proj_p90: number;
  proj_minutes: number; eligible: boolean; reasons: string[]; factors: string[]; risks: string[];
  data_quality: Record<string, unknown>; record_type: string; published: boolean; status: string;
  result: string | null; actual: number | null; actual_minutes: number | null; error_tags: string[] | null;
  created_at: string; odds_fetched_at: string; game?: string; start_time?: string; risk_level: string;
  closing_price: number | null; closing_line: number | null; team?: string; opponent?: string;
};
export type Recs = { picks: Pred[]; withdrawn: Pred[]; disclaimer: string };
export type Block = {
  n: number; wins: number; losses: number; pushes: number; voids: number; win_rate: number | null;
  units: number; roi: number | null; expected_roi: number | null; max_drawdown: number;
  brier?: number; brier_market?: number; log_loss?: number; avg_clv: number | null;
  calibration?: { bin: string; n: number; mean_pred: number; obs_rate: number }[];
};
export type Run = {
  id: number; type: string; date: string; status: string; started_at: string; finished_at: string | null;
  error: string | null; summary: RunSummary | null;
};
export type RunSummary = {
  date?: string; warning?: string; error?: string; model_version?: string;
  steps?: Record<string, unknown>;
  analysis?: { games: number; projections: number; props_evaluated: number; eligible: number; recommended: number; withdrawn: number };
};
export type Health = {
  time_et: string; latest_box_score_date: string | null; player_game_rows: number; injury_report_fresh: boolean;
  odds_feed_configured: boolean; latest_odds_fetched_at: string | null; latest_injury_fetched_at: string | null;
  odds_credits_remaining: string | number | null; odds_credits_checked_at: string | null;
  odds_markets: string[]; odds_fetch_runs: string[];
  production_model: { id: number; name: string; version: string; trained_through: string } | null;
  recent_runs: { id: number; type: string; status: string; started_at: string; finished_at: string | null; error: string | null; summary: RunSummary | null }[];
};
export type CalBin = { bin: string; n: number; mean_pred: number; obs_rate: number };
export type ModelInfo = {
  id: number; name: string; version: string; status: string; trained_through: string | null; created_at: string;
  promoted_at: string | null; notes: string | null; dispersion: Record<string, number> | null;
  metrics: {
    gate?: { pass: boolean; reasons: string[]; type: string };
    date_range?: string[]; n_predictions?: number; label?: string;
    markets?: Record<string, { brier_model: number; brier_naive: number; ece_model: number; n: number; calibration: CalBin[] }>;
  };
};
export type LogRow = {
  date: string; game_id: string; season: number; season_type: number; opp: string; home: boolean; starter: boolean;
  dnp: boolean; minutes: number; pts: number; reb: number; ast: number; fg3m: number; stl: number; blk: number;
  tov: number; pf: number; fga: number; fgm: number; fta: number;
};
export type Split = { minutes: number | null; pts: number | null; reb: number | null; ast: number | null; fg3m: number | null; games: number };
export type ProjMarkets = Record<string, { mean: number; p10: number; p50: number; p90: number }>;
export type PlayerDetail = {
  player: { id: string; name: string; position: string | null; team: string | null };
  injury: { status: string; detail: string | null } | null;
  injury_history: { status: string; detail: string | null; first_seen: string }[];
  splits: Record<string, Split>; game_log: LogRow[];
  latest_projection: { game_id: string; minutes: number; sd_minutes: number; markets: ProjMarkets; created_at: string } | null;
  prop_history: Pred[];
};
export type PlayerHit = { id: string; name: string; position: string | null; team: string | null };
export type SettledRow = {
  id: number; player: string; market: string; market_label: string; side: string; line: number;
  proj_mean: number; actual: number; result: string;
};
export type ParlayResult = {
  status: string; method: string;
  legs: { id: number; player: string; market_label: string; side: string; line: number; book: string; price: number; model_prob: number; game_id: string; eligible: boolean; published: boolean }[];
  pairs: { a: string; b: string; a_market: string; b_market: string; basis: string; rho: number; shared_games: number; sufficient_history: boolean }[];
  independent_prob: number; joint_prob: number; joint_low: number; joint_high: number; sensitivity_note: string;
  multiplied_decimal: number; price: { decimal: number; american: number; source: "quoted" | "multiplied" } | null;
  ev: number | null; ev_low: number | null; ev_high: number | null; risk_level: string;
  warnings: { level: "warning" | "serious"; code: string; message: string }[]; computed_at: string;
};
export type Note = { id: number; kind: string; title: string; body: string; created_at: string };
export type Prefs = {
  preferred_book: string; bankroll_units: number; preferred_markets: string[]; max_parlay_legs: number;
  min_ev: number; risk_tolerance: string; alert_channels: string[]; teams_filter: string[];
};
