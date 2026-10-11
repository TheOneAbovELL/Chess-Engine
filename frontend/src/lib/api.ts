// Typed client for the ChessLab REST API. Every call goes through `request`,
// which turns the backend's error envelope into an `ApiError`.

import type {
  AnalysisSnapshot,
  AppConfig,
  ClassificationThresholds,
  CompareResult,
  DataInfo,
  EngineDescriptor,
  EngineId,
  EngineSettings,
  EvalBreakdown,
  ExplorerResponse,
  GameDetail,
  GameSource,
  GameSummary,
  Health,
  ImportJob,
  ImportParams,
  Page,
  PgnParseResponse,
  PlayLevel,
  PositionInfo,
  Preferences,
  ProviderId,
  ProviderInfo,
  ProviderUser,
  Review,
  StatsSummary,
  UploadSummary,
} from "@/types/api";

export const API_BASE = "/api/v1";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof TypeError) return "Cannot reach the ChessLab server. Is the backend running?";
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

type Query = Record<string, string | number | boolean | null | undefined | string[]>;

export function toQuery(params: Query): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => search.append(key, v));
    else search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

async function request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  if (response.status === 204) return undefined as T;
  const isJson = response.headers.get("content-type")?.includes("application/json");
  const payload: unknown = isJson ? await response.json() : await response.text();
  if (!response.ok) {
    const envelope = (payload as { error?: { code?: string; message?: string; details?: unknown } })?.error;
    throw new ApiError(
      response.status,
      envelope?.code ?? "http_error",
      envelope?.message ?? `Request failed (HTTP ${response.status}).`,
      envelope?.details,
    );
  }
  return payload as T;
}

export interface PositionPayload {
  fen?: string | null;
  moves?: string[];
}

export interface GameQuery {
  q?: string;
  source?: string;
  owner?: string;
  color?: string;
  result?: string;
  time_class?: string;
  rated?: boolean;
  date_from?: string;
  date_to?: string;
  opening?: string;
  reviewed?: boolean;
  sort?: string;
  page?: number;
  page_size?: number;
}

export const api = {
  health: () => request<Health>("GET", "/health"),
  config: () => request<AppConfig>("GET", "/config"),
  engines: () => request<EngineDescriptor[]>("GET", "/engines"),
  levels: () => request<Record<EngineId, PlayLevel[]>>("GET", "/engines/levels"),
  stopEngine: (id: EngineId) => request<{ stopped: boolean }>("POST", `/engines/${id}/stop`),
  evaluate: (fen: string) => request<EvalBreakdown>("GET", `/engines/custom/evaluate${toQuery({ fen })}`),

  validate: (p: PositionPayload) => request<PositionInfo>("POST", "/positions/validate", p),
  parsePgn: (pgn: string) => request<PgnParseResponse>("POST", "/pgn/parse", { pgn }),
  analyse: (p: PositionPayload & { engine?: EngineId; depth?: number; movetime_ms?: number; multipv?: number }) =>
    request<AnalysisSnapshot>("POST", "/analysis", p),
  bestMove: (p: PositionPayload & { engine?: EngineId; level?: number; depth?: number; movetime_ms?: number }, signal?: AbortSignal) =>
    request<AnalysisSnapshot>("POST", "/analysis/best-move", p, signal),
  compare: (p: PositionPayload & { engines: EngineId[]; depth?: number; movetime_ms?: number; multipv?: number }) =>
    request<CompareResult[]>("POST", "/analysis/compare", p),

  owners: () => request<{ source: GameSource; username: string; games: number }[]>("GET", "/games/owners"),
  games: (q: GameQuery) => request<Page<GameSummary>>("GET", `/games${toQuery({ ...q })}`),
  game: (id: number) => request<GameDetail>("GET", `/games/${id}`),
  deleteGame: (id: number) => request<void>("DELETE", `/games/${id}`),
  deleteGames: (ids: number[]) => request<{ deleted: number }>("POST", "/games/delete", { ids }),
  importPgn: (pgn: string, owner?: string) => request<UploadSummary>("POST", "/games/import-pgn", { pgn, owner: owner || null }),
  saveGame: (pgn: string, owner?: string) => request<UploadSummary>("POST", "/games/save", { pgn, owner: owner || null }),
  exportUrl: (q: GameQuery) => `${API_BASE}/games/export.pgn${toQuery({ ...q, page: undefined, page_size: undefined, sort: undefined })}`,
  gamePgnUrl: (id: number) => `${API_BASE}/games/${id}/pgn`,

  startReview: (gameId: number, body: { engine?: EngineId; depth?: number; movetime_ms?: number; multipv?: number; force?: boolean }) =>
    request<Review>("POST", `/games/${gameId}/review`, body),
  latestReview: (gameId: number) => request<Review | null>("GET", `/games/${gameId}/review`),
  review: (id: number) => request<Review>("GET", `/reviews/${id}`),
  cancelReview: (id: number) => request<Review>("POST", `/reviews/${id}/cancel`),
  retryReview: (id: number) => request<Review>("POST", `/reviews/${id}/retry`),
  reclassify: (id: number) => request<Review>("POST", `/reviews/${id}/reclassify`),
  reviewQueue: () => request<(Review & { white: string; black: string })[]>("GET", "/reviews/queue"),
  batchReview: (gameIds: number[], body: { engine?: EngineId; depth?: number }) =>
    request<unknown[]>("POST", "/reviews/batch", { game_ids: gameIds, ...body }),

  providers: () => request<ProviderInfo[]>("GET", "/providers"),
  lookupUser: (provider: ProviderId, username: string) =>
    request<ProviderUser>("GET", `/providers/${provider}/users/${encodeURIComponent(username)}`),
  startImport: (params: ImportParams) => request<ImportJob>("POST", "/imports", params),
  refreshAll: () => request<ImportJob[]>("POST", "/imports/refresh-all"),
  imports: () => request<ImportJob[]>("GET", "/imports?limit=15"),
  importJob: (id: string) => request<ImportJob>("GET", `/imports/${id}`),
  cancelImport: (id: string) => request<ImportJob>("POST", `/imports/${id}/cancel`),
  retryImport: (id: string) => request<ImportJob>("POST", `/imports/${id}/retry`),

  stats: (q: GameQuery) => request<StatsSummary>("GET", `/stats/summary${toQuery({ ...q })}`),
  explorer: (moves: string[], q: GameQuery) => request<ExplorerResponse>("GET", `/explorer${toQuery({ ...q, moves })}`),

  engineSettings: () => request<EngineSettings>("GET", "/settings/engine"),
  saveEngineSettings: (s: EngineSettings) => request<EngineSettings>("PUT", "/settings/engine", s),
  thresholds: () => request<ClassificationThresholds>("GET", "/settings/classification"),
  saveThresholds: (t: ClassificationThresholds) => request<ClassificationThresholds>("PUT", "/settings/classification", t),
  preferences: () => request<Preferences>("GET", "/settings/preferences"),
  savePreferences: (p: Preferences) => request<Preferences>("PUT", "/settings/preferences", p),

  dataInfo: () => request<DataInfo>("GET", "/data/info"),
  backup: () => request<{ name: string; bytes: number }>("POST", "/data/backup"),
  deleteAllGames: () => request<{ deleted: number }>("DELETE", "/data/games?confirm=DELETE"),
};
