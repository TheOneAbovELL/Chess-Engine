import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Download, ExternalLink, FileDown, Filter, Library, Microscope, Search, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Badge, Button, Callout, ConfirmDialog, EmptyState, IconButton, PageHeader, Panel, Skeleton } from "@/components/ui";
import { api, errorMessage, type GameQuery } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatDate, plural, SOURCE_LABEL, TIME_CLASS_LABEL } from "@/lib/format";
import { toast } from "@/stores/toast";
import type { GameSummary } from "@/types/api";

const FILTER_KEYS = ["q", "source", "owner", "color", "result", "time_class", "date_from", "date_to", "opening", "reviewed", "sort"] as const;
const PAGE_SIZE = 25;

export function ResultBadge({ game }: { game: Pick<GameSummary, "user_result" | "result"> }) {
  if (game.user_result === "win") return <Badge tone="good">Won</Badge>;
  if (game.user_result === "loss") return <Badge tone="bad">Lost</Badge>;
  if (game.user_result === "draw") return <Badge>Draw</Badge>;
  return <Badge>{game.result === "*" ? "Unfinished" : game.result}</Badge>;
}

function ReviewBadge({ game }: { game: GameSummary }) {
  const status = game.review?.status;
  if (!status) return <span className="text-xs text-ink-500">–</span>;
  if (status === "completed") {
    const side = game.user_color ? game.review?.summary?.[game.user_color] : null;
    const blunders = side?.counts.blunder ?? 0;
    return (
      <Badge tone={blunders ? "warn" : "good"}>
        Reviewed{side ? ` · ${blunders} blunder${blunders === 1 ? "" : "s"}` : ""}
      </Badge>
    );
  }
  if (status === "queued" || status === "running") return <Badge tone="info">Reviewing…</Badge>;
  return <Badge tone="bad">{status}</Badge>;
}

export default function GamesPage() {
  const [params, setParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [confirmDelete, setConfirmDelete] = useState<number[] | null>(null);
  const [showFilters, setShowFilters] = useState(false);

  const filters: GameQuery = useMemo(() => {
    const q: GameQuery = { page: Number(params.get("page") ?? "1") || 1, page_size: PAGE_SIZE };
    for (const key of FILTER_KEYS) {
      const value = params.get(key);
      if (value === null || value === "") continue;
      if (key === "reviewed") q.reviewed = value === "true";
      else (q as Record<string, string>)[key] = value;
    }
    return q;
  }, [params]);

  const games = useQuery({ queryKey: ["games", filters], queryFn: () => api.games(filters), placeholderData: keepPreviousData });
  const owners = useQuery({ queryKey: ["owners"], queryFn: api.owners });

  const setFilter = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("page");
    setParams(next, { replace: true });
    setSelected(new Set());
  };
  const setPage = (page: number) => {
    const next = new URLSearchParams(params);
    next.set("page", String(page));
    setParams(next);
    setSelected(new Set());
  };
  const activeFilters = FILTER_KEYS.filter((k) => k !== "sort" && params.get(k));

  const remove = useMutation({
    mutationFn: (ids: number[]) => (ids.length === 1 ? api.deleteGame(ids[0]!).then(() => ({ deleted: 1 })) : api.deleteGames(ids)),
    onSuccess: (data) => {
      toast.success(`Deleted ${plural(data.deleted, "game")}`);
      setSelected(new Set());
      setConfirmDelete(null);
      void queryClient.invalidateQueries({ queryKey: ["games"] });
      void queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });
  const review = useMutation({
    mutationFn: (ids: number[]) => api.batchReview(ids, {}),
    onSuccess: (_d, ids) => {
      toast.success(`Queued ${plural(ids.length, "review")}`, "Reviews run one at a time in the background.");
      setSelected(new Set());
      void queryClient.invalidateQueries({ queryKey: ["games"] });
    },
  });

  const items = games.data?.items ?? [];
  const total = games.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const page = filters.page ?? 1;
  const allSelected = items.length > 0 && items.every((g) => selected.has(g.id));
  const noGamesAtAll = games.isSuccess && total === 0 && activeFilters.length === 0;

  return (
    <div>
      <PageHeader
        title="Game History"
        description="Every game stored on this computer: imported from Chess.com or Lichess, uploaded as PGN, or played here."
        actions={
          <>
            <a href={api.exportUrl(filters)} download>
              <Button icon={<FileDown className="size-4" />} disabled={!total}>
                Export {activeFilters.length ? "filtered" : "all"} as PGN
              </Button>
            </a>
            <Link to="/import">
              <Button variant="primary" icon={<Download className="size-4" />}>
                Import games
              </Button>
            </Link>
          </>
        }
      />

      {noGamesAtAll ? (
        <Panel>
          <EmptyState
            icon={<Library className="size-6" />}
            title="Your library is empty"
            actions={
              <>
                <Link to="/import">
                  <Button variant="primary">Import from Chess.com or Lichess</Button>
                </Link>
                <Link to="/play">
                  <Button>Play a game</Button>
                </Link>
              </>
            }
          >
            Import your public games with just your username (no password needed), or upload a PGN file. Everything stays in a local database on this computer.
          </EmptyState>
        </Panel>
      ) : (
        <Panel>
          {/* Filter bar */}
          <div className="flex flex-wrap items-center gap-2 border-b border-ink-700/70 p-3">
            <div className="relative min-w-[200px] flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-ink-400" />
              <input
                className="field pl-8"
                placeholder="Search by player name"
                defaultValue={params.get("q") ?? ""}
                onKeyDown={(e) => e.key === "Enter" && setFilter("q", (e.target as HTMLInputElement).value.trim() || null)}
                onBlur={(e) => e.target.value.trim() !== (params.get("q") ?? "") && setFilter("q", e.target.value.trim() || null)}
                aria-label="Search by player name"
              />
            </div>
            <select className="field w-auto" value={params.get("result") ?? ""} onChange={(e) => setFilter("result", e.target.value || null)} aria-label="Result">
              <option value="">All results</option>
              <option value="win">Wins</option>
              <option value="draw">Draws</option>
              <option value="loss">Losses</option>
            </select>
            <select className="field w-auto" value={params.get("time_class") ?? ""} onChange={(e) => setFilter("time_class", e.target.value || null)} aria-label="Time control">
              <option value="">All time controls</option>
              {Object.entries(TIME_CLASS_LABEL).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
            <select className="field w-auto" value={params.get("sort") ?? "played_desc"} onChange={(e) => setFilter("sort", e.target.value === "played_desc" ? null : e.target.value)} aria-label="Sort">
              <option value="played_desc">Newest first</option>
              <option value="played_asc">Oldest first</option>
              <option value="rating_desc">Highest rating</option>
              <option value="length_desc">Longest</option>
              <option value="imported_desc">Recently imported</option>
            </select>
            <Button variant={showFilters ? "secondary" : "ghost"} icon={<Filter className="size-4" />} onClick={() => setShowFilters((v) => !v)} aria-expanded={showFilters}>
              More filters{activeFilters.length ? ` (${activeFilters.length})` : ""}
            </Button>
          </div>
          {showFilters && (
            <div className="grid gap-3 border-b border-ink-700/70 p-3 sm:grid-cols-2 lg:grid-cols-4">
              <select className="field" value={params.get("owner") ?? ""} onChange={(e) => setFilter("owner", e.target.value || null)} aria-label="Account">
                <option value="">All accounts</option>
                {owners.data?.map((o) => (
                  <option key={`${o.source}-${o.username}`} value={o.username}>
                    {o.username} ({SOURCE_LABEL[o.source]}, {o.games})
                  </option>
                ))}
              </select>
              <select className="field" value={params.get("source") ?? ""} onChange={(e) => setFilter("source", e.target.value || null)} aria-label="Source">
                <option value="">All sources</option>
                {Object.entries(SOURCE_LABEL).map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
              <select className="field" value={params.get("color") ?? ""} onChange={(e) => setFilter("color", e.target.value || null)} aria-label="Your colour">
                <option value="">Either colour</option>
                <option value="white">You played White</option>
                <option value="black">You played Black</option>
              </select>
              <select className="field" value={params.get("reviewed") ?? ""} onChange={(e) => setFilter("reviewed", e.target.value || null)} aria-label="Review status">
                <option value="">Reviewed or not</option>
                <option value="true">Reviewed</option>
                <option value="false">Not reviewed</option>
              </select>
              <label className="space-y-1 text-xs text-ink-300">
                From
                <input type="date" className="field" value={params.get("date_from") ?? ""} onChange={(e) => setFilter("date_from", e.target.value || null)} />
              </label>
              <label className="space-y-1 text-xs text-ink-300">
                To
                <input type="date" className="field" value={params.get("date_to") ?? ""} onChange={(e) => setFilter("date_to", e.target.value || null)} />
              </label>
              <label className="space-y-1 text-xs text-ink-300 sm:col-span-2">
                Opening or ECO
                <input
                  className="field"
                  placeholder="e.g. Sicilian or B90"
                  defaultValue={params.get("opening") ?? ""}
                  onKeyDown={(e) => e.key === "Enter" && setFilter("opening", (e.target as HTMLInputElement).value.trim() || null)}
                  onBlur={(e) => setFilter("opening", e.target.value.trim() || null)}
                />
              </label>
            </div>
          )}
          {activeFilters.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 border-b border-ink-700/70 px-3 py-2">
              {activeFilters.map((key) => (
                <button key={key} type="button" className="chip hover:border-ink-500" onClick={() => setFilter(key, null)}>
                  {key.replace("_", " ")}: {params.get(key)} <X className="size-3" />
                </button>
              ))}
              <Button size="sm" variant="ghost" onClick={() => setParams(new URLSearchParams(), { replace: true })}>
                Clear all
              </Button>
            </div>
          )}

          {selected.size > 0 && (
            <div className="flex flex-wrap items-center gap-2 border-b border-ink-700/70 bg-ink-800/60 px-3 py-2 text-sm">
              <span className="text-ink-200">{plural(selected.size, "game")} selected</span>
              <Button size="sm" icon={<Microscope className="size-3.5" />} loading={review.isPending} onClick={() => review.mutate([...selected])}>
                Review selected
              </Button>
              <Button size="sm" variant="danger" icon={<Trash2 className="size-3.5" />} onClick={() => setConfirmDelete([...selected])}>
                Delete selected
              </Button>
            </div>
          )}

          {games.isError && (
            <div className="p-4">
              <Callout tone="bad" title="Could not load games">
                {errorMessage(games.error)}
              </Callout>
            </div>
          )}

          {games.isPending ? (
            <div className="space-y-3 p-4">
              {Array.from({ length: 6 }, (_, i) => (
                <Skeleton key={i} className="h-10" />
              ))}
            </div>
          ) : items.length === 0 ? (
            <EmptyState title="No games match these filters" actions={<Button onClick={() => setParams(new URLSearchParams())}>Clear filters</Button>} />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-sm">
                <thead>
                  <tr className="border-b border-ink-700/70 text-left text-[11px] uppercase tracking-wider text-ink-400">
                    <th className="w-10 px-3 py-2">
                      <input
                        type="checkbox"
                        aria-label="Select all on this page"
                        checked={allSelected}
                        onChange={() => setSelected(allSelected ? new Set() : new Set(items.map((g) => g.id)))}
                        className="accent-[var(--color-brass-500)]"
                      />
                    </th>
                    <th className="px-2 py-2 font-medium">Date</th>
                    <th className="px-2 py-2 font-medium">Players</th>
                    <th className="px-2 py-2 font-medium">Result</th>
                    <th className="px-2 py-2 font-medium">Type</th>
                    <th className="px-2 py-2 font-medium">Opening</th>
                    <th className="px-2 py-2 font-medium">Review</th>
                    <th className="px-2 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {items.map((game) => (
                    <tr key={game.id} className={cn("border-b border-ink-800 transition-colors hover:bg-ink-800/50", selected.has(game.id) && "bg-brass-500/5")}>
                      <td className="px-3 py-2.5">
                        <input
                          type="checkbox"
                          aria-label={`Select game ${game.white} vs ${game.black}`}
                          checked={selected.has(game.id)}
                          onChange={() =>
                            setSelected((s) => {
                              const next = new Set(s);
                              if (next.has(game.id)) next.delete(game.id);
                              else next.add(game.id);
                              return next;
                            })
                          }
                          className="accent-[var(--color-brass-500)]"
                        />
                      </td>
                      <td className="num whitespace-nowrap px-2 py-2.5 text-xs text-ink-300">{formatDate(game.played_at)}</td>
                      <td className="px-2 py-2.5">
                        <Link to={`/games/${game.id}`} className="group block">
                          <PlayerName name={game.white} elo={game.white_elo} me={game.user_color === "white"} color="w" />
                          <PlayerName name={game.black} elo={game.black_elo} me={game.user_color === "black"} color="b" />
                        </Link>
                      </td>
                      <td className="px-2 py-2.5">
                        <ResultBadge game={game} />
                        <span className="num ml-1.5 text-xs text-ink-400">{game.result}</span>
                      </td>
                      <td className="px-2 py-2.5 text-xs text-ink-300">
                        <div>{TIME_CLASS_LABEL[game.time_class] ?? game.time_class}</div>
                        <div className="text-ink-500">{SOURCE_LABEL[game.source]}</div>
                      </td>
                      <td className="max-w-[220px] px-2 py-2.5 text-xs text-ink-300">
                        <div className="truncate" title={game.opening ?? undefined}>
                          {game.opening ?? "–"}
                        </div>
                        <div className="num text-ink-500">
                          {game.eco ?? ""} · {Math.ceil(game.ply_count / 2)} moves
                        </div>
                      </td>
                      <td className="px-2 py-2.5">
                        <ReviewBadge game={game} />
                      </td>
                      <td className="whitespace-nowrap px-2 py-2.5 text-right">
                        <Link to={`/games/${game.id}`}>
                          <Button size="sm" variant="ghost">
                            Open
                          </Button>
                        </Link>
                        <a href={api.gamePgnUrl(game.id)} download aria-label="Download PGN" title="Download PGN" className="inline-flex size-8 items-center justify-center rounded-lg text-ink-300 hover:bg-ink-750 hover:text-ink-50">
                          <FileDown className="size-4" />
                        </a>
                        {game.url && (
                          <a href={game.url} target="_blank" rel="noreferrer noopener" aria-label="Open on the original site" title="Open on the original site" className="inline-flex size-8 items-center justify-center rounded-lg text-ink-300 hover:bg-ink-750 hover:text-ink-50">
                            <ExternalLink className="size-4" />
                          </a>
                        )}
                        <IconButton label="Delete game" className="size-8" onClick={() => setConfirmDelete([game.id])}>
                          <Trash2 className="size-4" />
                        </IconButton>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="flex items-center justify-between gap-3 px-4 py-3 text-xs text-ink-300">
            <span>
              {total ? `${(page - 1) * PAGE_SIZE + 1}–${Math.min(page * PAGE_SIZE, total)} of ${total.toLocaleString()}` : "0 games"}
              {games.isFetching && !games.isPending ? " · updating…" : ""}
            </span>
            <div className="flex items-center gap-1">
              <IconButton label="Previous page" onClick={() => setPage(page - 1)} disabled={page <= 1}>
                <ChevronLeft className="size-4" />
              </IconButton>
              <span className="num px-2">
                {page} / {pages}
              </span>
              <IconButton label="Next page" onClick={() => setPage(page + 1)} disabled={page >= pages}>
                <ChevronRight className="size-4" />
              </IconButton>
            </div>
          </div>
        </Panel>
      )}

      <ConfirmDialog
        open={confirmDelete !== null}
        title={confirmDelete && confirmDelete.length > 1 ? `Delete ${confirmDelete.length} games?` : "Delete this game?"}
        message="The game and its engine review will be removed from your local library. Games imported from Chess.com or Lichess can be imported again later."
        confirmLabel="Delete"
        danger
        busy={remove.isPending}
        onCancel={() => setConfirmDelete(null)}
        onConfirm={() => confirmDelete && remove.mutate(confirmDelete)}
      />
    </div>
  );
}

function PlayerName({ name, elo, me, color }: { name: string; elo: number | null; me: boolean; color: "w" | "b" }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className={cn("size-2.5 shrink-0 rounded-sm border", color === "w" ? "border-ink-300 bg-eval-white" : "border-ink-500 bg-ink-950")} aria-hidden />
      <span className={cn("truncate group-hover:text-brass-300", me ? "font-semibold text-ink-50" : "text-ink-200")}>{name}</span>
      {elo && <span className="num text-xs text-ink-400">{elo}</span>}
    </div>
  );
}
