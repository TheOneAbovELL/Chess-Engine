// Types mirroring the backend's Pydantic schemas (backend/app/api/v1/schemas.py).

export type EngineId = "stockfish" | "custom";

/** White's point of view. `mate === 0` means the side to move is checkmated. */
export interface Evaluation {
  cp: number | null;
  mate: number | null;
}

export interface EngineLine {
  multipv: number;
  depth: number;
  seldepth: number | null;
  score: Evaluation;
  pv: string[];
  pv_san: string[];
}

export interface AnalysisSnapshot {
  engine_id: EngineId;
  engine_name: string;
  fen: string;
  depth: number;
  seldepth: number | null;
  nodes: number | null;
  nps: number | null;
  time_ms: number | null;
  hashfull: number | null;
  lines: EngineLine[];
  best_move: string | null;
  best_move_san: string | null;
  ponder: string | null;
  final: boolean;
  stop_reason: "limit" | "stopped" | "terminal" | null;
  terminal: string | null;
}

export interface EngineCapabilities {
  multipv: boolean;
  max_multipv: number;
  depth_limit: boolean;
  time_limit: boolean;
  node_limit: boolean;
  limit_strength: boolean;
  eval_breakdown: boolean;
  threads: boolean;
  hash: boolean;
}

export interface EngineDescriptor {
  id: EngineId;
  display_name: string;
  available: boolean;
  status: "stopped" | "starting" | "ready" | "busy" | "error" | "unavailable";
  name: string | null;
  author: string | null;
  detail: string | null;
  capabilities: EngineCapabilities;
}

export interface AppConfig {
  version: string;
  limits: {
    max_engine_threads: number;
    max_engine_hash_mb: number;
    max_search_depth: number;
    max_multipv: number;
    max_analysis_seconds: number;
    max_live_analysis_seconds: number;
    max_review_movetime_ms: number;
    max_pgn_bytes: number;
    max_import_games: number;
    max_batch_review_games: number;
  };
  providers: { id: ProviderId; name: string }[];
}

export interface Health {
  status: "ok" | "degraded";
  version: string;
  database: string;
  engines: Record<string, string>;
  workers: { imports: boolean; reviews: boolean };
}

export interface EngineSettings {
  default_engine: EngineId;
  stockfish_threads: number;
  stockfish_hash_mb: number;
  custom_hash_mb: number;
  analysis_multipv: number;
  analysis_depth: number | null;
  analysis_movetime_ms: number | null;
  review_engine: EngineId;
  review_depth: number;
  review_movetime_ms: number;
  review_multipv: number;
  review_threads: number;
}

export interface ClassificationThresholds {
  excellent: number;
  good: number;
  inaccuracy: number;
  mistake: number;
}

export type ProviderId = "chesscom" | "lichess";

export interface Preferences {
  accounts: { provider: ProviderId; username: string }[];
}

export interface PositionInfo {
  fen: string;
  turn: "white" | "black";
  is_check: boolean;
  is_game_over: boolean;
  outcome: string | null;
  result: string | null;
  can_claim_draw: boolean;
  legal_moves: { uci: string; san: string }[];
}

export interface ServerTreeNode {
  id: number;
  parent: number | null;
  ply: number;
  fen: string;
  san: string | null;
  uci: string | null;
  comment: string | null;
  nags: number[];
  clock: number | null;
  children: number[];
}

export interface PgnParseResponse {
  headers: Record<string, string>;
  nodes: ServerTreeNode[];
  games_in_text: number;
}

export type GameSource = "chesscom" | "lichess" | "pgn" | "local";
export type TimeClass = "ultrabullet" | "bullet" | "blitz" | "rapid" | "classical" | "correspondence" | "unknown";
export type UserResult = "win" | "loss" | "draw";

export interface ReviewBrief {
  id: number;
  status: JobStatus;
  summary: ReviewSummary | null;
}

export interface GameSummary {
  id: number;
  source: GameSource;
  external_id: string;
  owner_username: string | null;
  white: string;
  black: string;
  white_elo: number | null;
  black_elo: number | null;
  result: string;
  termination: string | null;
  user_color: "white" | "black" | null;
  user_result: UserResult | null;
  user_rating: number | null;
  opponent: string | null;
  opponent_rating: number | null;
  time_control: string | null;
  time_class: TimeClass;
  rated: boolean | null;
  eco: string | null;
  opening: string | null;
  url: string | null;
  played_at: string | null;
  imported_at: string;
  ply_count: number;
  review: ReviewBrief | null;
}

export interface GameMove {
  ply: number;
  san: string;
  uci: string;
  fen: string;
  clock: number | null;
}

export interface GameDetail extends GameSummary {
  pgn: string;
  initial_fen: string;
  moves: GameMove[];
  headers: Record<string, string>;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface UploadSummary {
  total: number;
  imported: number;
  duplicates: number;
  failed: number;
  skipped: number;
  game_ids: number[];
  errors: { index: number; game: string | null; error: string }[];
}

export type JobStatus = "queued" | "running" | "completed" | "partial" | "failed" | "cancelled";

export interface ImportParams {
  provider: ProviderId;
  username: string;
  mode: "recent" | "all" | "refresh";
  max_games: number;
  since?: string | null;
  until?: string | null;
  time_classes?: Exclude<TimeClass, "unknown">[];
  color?: "white" | "black" | null;
  rated?: boolean | null;
}

export interface ImportJob {
  id: string;
  provider: ProviderId;
  username: string;
  params: ImportParams;
  status: JobStatus;
  discovered: number;
  imported: number;
  duplicates: number;
  failed: number;
  skipped: number;
  phase: string | null;
  message: string | null;
  errors: { ref: string; error: string }[];
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface ProviderInfo {
  id: ProviderId;
  name: string;
  docs: string;
  notes: string[];
}

export interface ProviderUser {
  provider: ProviderId;
  username: string;
  exists: boolean;
  url: string | null;
  display_name: string | null;
  status: string | null;
  closed: boolean;
  joined: string | null;
  last_online: string | null;
  game_counts: Record<string, number>;
  notes: string[];
}

export type MoveClass = "best" | "excellent" | "good" | "inaccuracy" | "mistake" | "blunder" | "forced";

export interface SideSummary {
  moves: number;
  counts: Record<MoveClass, number>;
  acpl: number | null;
  avg_win_loss: number | null;
}

export interface ReviewSummary {
  white: SideSummary;
  black: SideSummary;
}

export interface ReviewLine {
  multipv: number;
  eval: Evaluation;
  depth: number;
  pv: string[];
  pv_san: string[];
}

export interface PositionReview {
  ply: number;
  fen: string;
  eval: Evaluation;
  depth: number | null;
  nodes: number | null;
  best_move_uci: string | null;
  best_move_san: string | null;
  lines: ReviewLine[];
  terminal: string | null;
  move_uci: string | null;
  move_san: string | null;
  classification: MoveClass | null;
  cp_loss: number | null;
  win_loss: number | null;
  clock_s: number | null;
}

export interface Review {
  id: number;
  game_id: number;
  status: JobStatus;
  engine_id: EngineId;
  engine_name: string | null;
  settings: { depth: number; movetime_ms: number; multipv: number };
  thresholds: ClassificationThresholds;
  progress_done: number;
  progress_total: number;
  error: string | null;
  summary: ReviewSummary | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  positions?: PositionReview[];
}

export interface WDL {
  games: number;
  wins: number;
  draws: number;
  losses: number;
  score: number | null;
}

export interface Insight {
  kind: string;
  title: string;
  detail: string;
  sample_size: number;
  confidence: "low" | "medium" | "high";
}

export interface StatsSummary {
  totals: WDL & { all_games: number; without_perspective: number; first_game: string | null; last_game: string | null };
  by_color: { white: WDL; black: WDL };
  by_time_class: (WDL & { time_class: TimeClass })[];
  rating_trend: Record<string, { date: string; rating: number; game_id: number }[]>;
  openings: (WDL & { name: string; as_white: WDL; as_black: WDL })[];
  game_length: { average_moves: number | null; by_result: Record<UserResult, number | null> };
  endings: Record<string, { win: number; loss: number; draw: number }>;
  recent: { last_20: WDL; previous_20: WDL };
  move_quality: {
    reviewed_games: number;
    moves: number;
    counts: Record<Exclude<MoveClass, "forced">, number>;
    by_phase: Record<"opening" | "middlegame" | "endgame", { moves: number; mistakes_and_blunders: number; rate: number | null }>;
  };
  insights: Insight[];
  owners: { source: GameSource; username: string; games: number }[];
}

export interface ExplorerMove {
  uci: string;
  san: string;
  games: number;
  wins: number;
  draws: number;
  losses: number;
  score: number | null;
  share: number;
  last_played: string | null;
  game_ids: number[];
}

export interface ExplorerResponse {
  fen: string;
  total_games: number;
  moves: ExplorerMove[];
  max_ply: number;
}

export interface EvalBreakdown {
  phase: number;
  max_phase: number;
  components: Record<string, number>;
  total_white_pov: number;
  perspective: "white";
}

export interface CompareResult {
  engine_id: EngineId;
  snapshot: AnalysisSnapshot | null;
  error: string | null;
}

export interface DataInfo {
  games: number;
  completed_reviews: number;
  import_jobs: number;
  database_bytes: number | null;
  storage: string;
  backups: { name: string; bytes: number }[];
}

export interface PlayLevel {
  level: number;
  label: string;
}
