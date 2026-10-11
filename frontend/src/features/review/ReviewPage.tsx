import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink, FileDown, Microscope, RefreshCw, RotateCcw, Square, Target } from "lucide-react";
import { useMemo, useState, type CSSProperties } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { Badge, Button, Callout, EmptyState, Field, Panel, PanelHeader, ProgressBar, Segmented, Skeleton, Toggle } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { describeEval, formatEval, MOVE_CLASS_META, MOVE_CLASS_ORDER } from "@/lib/eval";
import { formatClock, formatDate, SOURCE_LABEL, TIME_CLASS_LABEL } from "@/lib/format";
import { fromMoves } from "@/lib/tree";
import { useAnalysisStore } from "@/stores/analysis";
import { usePreferences } from "@/stores/preferences";
import { toast } from "@/stores/toast";
import type { EngineId, GameDetail, MoveClass, PositionReview, Review } from "@/types/api";
import { BoardNav, useBoardKeys } from "../board/BoardControls";
import { ChessBoard } from "../board/ChessBoard";
import { EvalBar } from "../board/EvalBar";
import { MoveTree } from "../board/MoveTree";
import { ResultBadge } from "../games/GamesPage";
import { EvalGraph } from "./EvalGraph";

const ACTIVE = ["queued", "running"];

export default function ReviewPage() {
  const { gameId } = useParams();
  const id = Number(gameId);
  const game = useQuery({ queryKey: ["game", id], queryFn: () => api.game(id), enabled: Number.isFinite(id) });

  if (game.isPending)
    return (
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
        <Skeleton className="aspect-square w-full max-w-[640px]" />
        <div className="space-y-3">
          <Skeleton className="h-24" />
          <Skeleton className="h-64" />
        </div>
      </div>
    );
  if (game.isError)
    return (
      <Panel>
        <EmptyState title="Game not available" actions={<Link to="/games"><Button>Back to games</Button></Link>}>
          {errorMessage(game.error)}
        </EmptyState>
      </Panel>
    );
  return <ReviewView game={game.data} />;
}

function ReviewView({ game }: { game: GameDetail }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const loadAnalysis = useAnalysisStore((s) => s.load);
  const { showBestArrow } = usePreferences();
  const [ply, setPly] = useState(0);
  const [orientation, setOrientation] = useState<"white" | "black">(game.user_color === "black" ? "black" : "white");

  const tree = useMemo(() => fromMoves(game.initial_fen, game.moves.map((m) => m.uci), game.headers), [game]);
  const maxPly = game.moves.length;

  const review = useQuery({
    queryKey: ["review", game.id],
    queryFn: () => api.latestReview(game.id),
    refetchInterval: (q) => (q.state.data && ACTIVE.includes(q.state.data.status) ? 1500 : false),
  });
  const data = review.data ?? null;
  const positions = useMemo(() => (data?.status === "completed" ? (data.positions ?? []) : []), [data]);
  const byPly = useMemo(() => new Map(positions.map((p) => [p.ply, p])), [positions]);

  const current = byPly.get(ply);
  const previous = ply > 0 ? byPly.get(ply - 1) : undefined;
  const fen = ply === 0 ? game.initial_fen : game.moves[ply - 1]!.fen;
  const turn = fen.split(" ")[1] === "b" ? "b" : "w";
  const move = ply > 0 ? game.moves[ply - 1] : undefined;

  const annotations = useMemo(() => {
    const map: Record<string, MoveClass | null> = {};
    for (const p of positions) if (p.ply > 0) map[`n${p.ply}`] = p.classification;
    return map;
  }, [positions]);

  const arrows = [];
  if (showBestArrow && current?.best_move_uci) arrows.push({ from: current.best_move_uci.slice(0, 2), to: current.best_move_uci.slice(2, 4), color: "rgba(127,178,255,0.85)" });
  const markers: Record<string, CSSProperties> = {};
  if (move && current?.classification) {
    const color = MOVE_CLASS_META[current.classification].color;
    markers[move.uci.slice(2, 4)] = { boxShadow: `inset 0 0 0 4px ${color}` };
  }

  const go = (p: number) => setPly(Math.max(0, Math.min(maxPly, p)));
  useBoardKeys({
    prev: () => setPly((p) => Math.max(0, p - 1)),
    next: () => setPly((p) => Math.min(maxPly, p + 1)),
    first: () => setPly(0),
    last: () => setPly(maxPly),
    flip: () => setOrientation((o) => (o === "white" ? "black" : "white")),
  });

  const openInAnalysis = () => {
    loadAnalysis(tree, `n${ply}`, orientation);
    navigate("/analysis");
  };

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["review", game.id] });
    void queryClient.invalidateQueries({ queryKey: ["games"] });
    void queryClient.invalidateQueries({ queryKey: ["stats"] });
  };

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Link to="/games" className="mb-1 inline-flex items-center gap-1 text-xs text-ink-400 hover:text-ink-200">
            <ArrowLeft className="size-3.5" /> Game History
          </Link>
          <h1 className="flex flex-wrap items-center gap-2 text-xl font-semibold text-ink-50">
            <span className={cn(game.user_color === "white" && "text-brass-300")}>{game.white}</span>
            <span className="num text-sm text-ink-400">{game.white_elo ?? ""}</span>
            <span className="text-ink-500">vs</span>
            <span className={cn(game.user_color === "black" && "text-brass-300")}>{game.black}</span>
            <span className="num text-sm text-ink-400">{game.black_elo ?? ""}</span>
          </h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-ink-300">
            <ResultBadge game={game} />
            <span className="num">{game.result}</span>
            <span>· {formatDate(game.played_at)}</span>
            <span>· {TIME_CLASS_LABEL[game.time_class]}{game.time_control ? ` (${game.time_control})` : ""}</span>
            <span>· {SOURCE_LABEL[game.source]}</span>
            {game.opening && <span className="truncate">· {game.eco ? `${game.eco} ` : ""}{game.opening}</span>}
            {game.termination && <span>· {game.termination}</span>}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button icon={<Microscope className="size-4" />} onClick={openInAnalysis}>
            Explore in analysis
          </Button>
          <a href={api.gamePgnUrl(game.id)} download>
            <Button icon={<FileDown className="size-4" />}>PGN</Button>
          </a>
          {game.url && (
            <a href={game.url} target="_blank" rel="noreferrer noopener">
              <Button variant="ghost" icon={<ExternalLink className="size-4" />}>
                Original
              </Button>
            </a>
          )}
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_440px]">
        <div className="min-w-0">
          <div className="mx-auto max-w-[min(100%,calc(100dvh-200px))] space-y-3">
            <div className="flex gap-3">
              <EvalBar evaluation={current?.eval ?? null} turn={turn} orientation={orientation} className="w-4 shrink-0 sm:w-6" />
              <div className="min-w-0 flex-1">
              <ChessBoard
                id="review-board"
                fen={fen}
                orientation={orientation}
                movable="none"
                lastMove={move ? { from: move.uci.slice(0, 2), to: move.uci.slice(2, 4) } : null}
                arrows={arrows}
                squareMarkers={markers}
                ariaLabel="Game review board"
              />
              </div>
            </div>
            <div className="pl-7 sm:pl-9">
              <BoardNav
                onFirst={() => go(0)}
                onPrev={() => go(ply - 1)}
                onNext={() => go(ply + 1)}
                onLast={() => go(maxPly)}
                onFlip={() => setOrientation((o) => (o === "white" ? "black" : "white"))}
                canBack={ply > 0}
                canForward={ply < maxPly}
              >
                <span className="num text-xs text-ink-400">
                  {ply}/{maxPly}
                </span>
              </BoardNav>
            </div>
          </div>
          {positions.length > 0 && (
            <Panel className="mt-4 px-2 pt-3">
              <EvalGraph positions={positions} currentPly={ply} onSelect={go} />
            </Panel>
          )}
        </div>

        <div className="min-w-0 space-y-4">
          <ReviewStatus game={game} review={data} loading={review.isPending} onChange={invalidate} />
          {data?.status === "completed" && (
            <>
              <MoveInsight ply={ply} move={move} current={current} previous={previous} turn={turn} clock={move?.clock ?? null} />
              <Panel>
                <PanelHeader title="Moves" subtitle="Symbols mark inaccuracies (?!), mistakes (?) and blunders (??)" />
                <div className="max-h-72 overflow-y-auto">
                  <MoveTree tree={tree} currentId={`n${ply}`} onSelect={(nodeId) => go(Number(nodeId.slice(1)))} annotations={annotations} />
                </div>
              </Panel>
              {data.summary && <SummaryPanel review={data} userColor={game.user_color} white={game.white} black={game.black} />}
            </>
          )}
          {data?.status !== "completed" && (
            <Panel>
              <PanelHeader title="Moves" />
              <div className="max-h-72 overflow-y-auto">
                <MoveTree tree={tree} currentId={`n${ply}`} onSelect={(nodeId) => go(Number(nodeId.slice(1)))} />
              </div>
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}

function ReviewStatus({ game, review, loading, onChange }: { game: GameDetail; review: Review | null; loading: boolean; onChange: () => void }) {
  const engines = useQuery({ queryKey: ["engines"], queryFn: api.engines });
  const settings = useQuery({ queryKey: ["settings", "engine"], queryFn: api.engineSettings });
  const [engine, setEngine] = useState<EngineId | null>(null);
  const [depth, setDepth] = useState<number | null>(null);
  const activeEngine = engine ?? settings.data?.review_engine ?? "stockfish";
  const activeDepth = depth ?? settings.data?.review_depth ?? 14;

  const start = useMutation({
    mutationFn: (force: boolean) => api.startReview(game.id, { engine: activeEngine, depth: activeDepth, force }),
    onSuccess: () => {
      toast.info("Review queued", "Positions are analysed in the background. You can keep using ChessLab.");
      onChange();
    },
    onError: (e) => toast.error("Could not start the review", errorMessage(e)),
  });
  const cancel = useMutation({ mutationFn: () => api.cancelReview(review!.id), onSuccess: onChange });
  const retry = useMutation({ mutationFn: () => api.retryReview(review!.id), onSuccess: onChange });

  if (loading) return <Skeleton className="h-28" />;

  if (review && ACTIVE.includes(review.status)) {
    return (
      <Panel>
        <PanelHeader title="Engine review in progress" subtitle={`${review.engine_id === "stockfish" ? "Stockfish" : "ChessLab Engine"} · depth ${review.settings.depth}`} actions={<Button size="sm" variant="ghost" icon={<Square className="size-3" />} loading={cancel.isPending} onClick={() => cancel.mutate()}>Cancel</Button>} />
        <div className="space-y-2 p-4">
          <ProgressBar value={review.progress_done} max={review.progress_total} label="Review progress" />
          <p className="num text-xs text-ink-300">
            {review.status === "queued" ? "Waiting for the review worker…" : `Analysed ${review.progress_done} of ${review.progress_total} positions`}
          </p>
        </div>
      </Panel>
    );
  }

  const setupForm = (
    <div className="grid gap-3 sm:grid-cols-2">
      <Field label="Engine">
        <Segmented
          size="sm"
          label="Engine"
          value={activeEngine}
          onChange={(v) => setEngine(v as EngineId)}
          options={(engines.data ?? []).map((e) => ({ value: e.id, label: e.display_name, disabled: !e.available }))}
        />
      </Field>
      <Field label={`Depth per position: ${activeDepth}`} hint="Higher is more accurate and slower.">
        <input type="range" min={8} max={22} value={activeDepth} onChange={(e) => setDepth(Number(e.target.value))} className="w-full accent-[var(--color-brass-500)]" aria-label="Depth per position" />
      </Field>
    </div>
  );

  if (!review || review.status === "cancelled" || review.status === "failed") {
    return (
      <Panel>
        <PanelHeader title="Engine review" icon={<Target className="size-4" />} />
        <div className="space-y-4 p-4">
          {review?.status === "failed" && (
            <Callout tone="bad" title="The last review failed">
              {review.error}
            </Callout>
          )}
          {review?.status === "cancelled" && <Callout tone="info" title="The last review was cancelled" />}
          <p className="text-sm text-ink-300">
            Analyse every position to find the best moves, your mistakes and how the evaluation changed. A 40-move game takes roughly a minute with Stockfish on a laptop.
          </p>
          {setupForm}
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" icon={<Target className="size-4" />} loading={start.isPending} onClick={() => start.mutate(true)}>
              Review this game
            </Button>
            {review && (review.status === "failed" || review.status === "cancelled") && (
              <Button icon={<RotateCcw className="size-4" />} loading={retry.isPending} onClick={() => retry.mutate()}>
                Resume previous review
              </Button>
            )}
          </div>
        </div>
      </Panel>
    );
  }

  return (
    <Panel>
      <details>
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3">
          <span className="text-sm">
            <span className="font-semibold text-ink-50">Reviewed</span>
            <span className="text-ink-400">
              {" "}
              · {review.engine_name ?? review.engine_id} · depth {review.settings.depth}
            </span>
          </span>
          <span className="flex items-center gap-1 text-xs text-ink-400">
            <RefreshCw className="size-3.5" /> Re-run
          </span>
        </summary>
        <div className="space-y-3 border-t border-ink-700/70 p-4">
          {setupForm}
          <Button size="sm" loading={start.isPending} onClick={() => start.mutate(true)}>
            Run a new review
          </Button>
        </div>
      </details>
    </Panel>
  );
}

function MoveInsight({ ply, move, current, previous, turn, clock }: { ply: number; move?: { san: string; uci: string }; current?: PositionReview; previous?: PositionReview; turn: "w" | "b"; clock: number | null }) {
  if (ply === 0 || !move) {
    return (
      <Panel className="p-4 text-sm text-ink-300">
        Start position{current ? ` · ${formatEval(current.eval, turn)} (${describeEval(current.eval, turn)})` : ""}. Use ← → or click the graph to step through the game.
      </Panel>
    );
  }
  const cls = current?.classification;
  const meta = cls ? MOVE_CLASS_META[cls] : null;
  const prevTurn = turn === "w" ? "b" : "w";
  const playedBest = previous?.best_move_uci === move.uci;
  const moveNo = `${Math.floor((ply - 1) / 2) + 1}${ply % 2 === 1 ? "." : "..."}`;
  return (
    <Panel>
      <div className="space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="num text-lg font-semibold text-ink-50">
            {moveNo} {move.san}
          </span>
          {meta && (
            <span className="rounded-full px-2 py-0.5 text-xs font-semibold text-ink-950" style={{ background: meta.color }}>
              {meta.label}
            </span>
          )}
          {clock !== null && <span className="num ml-auto text-xs text-ink-400">clock {formatClock(clock)}</span>}
        </div>
        {meta && <p className="text-xs text-ink-400">{meta.description}</p>}
        <dl className="num grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-lg bg-ink-900 px-3 py-2">
            <dt className="text-ink-400">Before</dt>
            <dd className="text-sm text-ink-50">{previous ? formatEval(previous.eval, prevTurn) : "–"}</dd>
          </div>
          <div className="rounded-lg bg-ink-900 px-3 py-2">
            <dt className="text-ink-400">After</dt>
            <dd className="text-sm text-ink-50">{current ? formatEval(current.eval, turn) : "–"}</dd>
          </div>
        </dl>
        {current?.win_loss !== null && current?.win_loss !== undefined && cls !== "forced" && (
          <p className="text-xs text-ink-300">
            Winning chances lost: <span className="num text-ink-50">{(current.win_loss * 100).toFixed(1)}%</span>
            {current.cp_loss ? (
              <>
                {" "}
                · centipawn loss <span className="num text-ink-50">{current.cp_loss}</span>
              </>
            ) : null}
          </p>
        )}
        {previous?.best_move_san && !playedBest && (
          <div className="rounded-lg border border-sky-line/30 bg-sky-line/5 p-3 text-sm">
            <p className="text-ink-200">
              Engine preferred <span className="num font-semibold text-sky-line">{previous.best_move_san}</span>
            </p>
            {previous.lines.length > 0 && (
              <ul className="num mt-2 space-y-1 text-xs text-ink-300">
                {previous.lines.map((line) => (
                  <li key={line.multipv} className="flex gap-2">
                    <span className="w-12 shrink-0 text-ink-100">{formatEval(line.eval, prevTurn)}</span>
                    <span className="truncate">{line.pv_san.slice(0, 7).join(" ")}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        {playedBest && <p className="text-xs text-q-best">This was the engine's top choice.</p>}
        {current?.terminal && <Badge tone="brass">{current.terminal.replace(/_/g, " ")}</Badge>}
      </div>
    </Panel>
  );
}

function SummaryPanel({ review, userColor, white, black }: { review: Review; userColor: "white" | "black" | null; white: string; black: string }) {
  const [showAll, setShowAll] = useState(false);
  const sides = (["white", "black"] as const).map((side) => ({ side, name: side === "white" ? white : black, data: review.summary![side] }));
  return (
    <Panel>
      <PanelHeader title="Summary" subtitle="ChessLab's own classification (see Settings → Review thresholds)" />
      <div className="grid grid-cols-2 divide-x divide-ink-700/70">
        {sides.map(({ side, name, data }) => (
          <div key={side} className="p-4">
            <p className={cn("truncate text-sm font-semibold", userColor === side ? "text-brass-300" : "text-ink-50")}>{name}</p>
            <p className="num mt-0.5 text-xs text-ink-400">
              avg. centipawn loss {data.acpl ?? "–"}
            </p>
            <ul className="mt-3 space-y-1.5">
              {MOVE_CLASS_ORDER.filter((c) => showAll || data.counts[c] > 0 || ["inaccuracy", "mistake", "blunder"].includes(c)).map((c) => (
                <li key={c} className="flex items-center justify-between text-xs">
                  <span className="flex items-center gap-2 text-ink-300">
                    <span className="size-2.5 rounded-full" style={{ background: MOVE_CLASS_META[c].color }} />
                    {MOVE_CLASS_META[c].label}
                  </span>
                  <span className="num text-ink-100">{data.counts[c]}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="border-t border-ink-700/70 px-4 py-2">
        <Toggle checked={showAll} onChange={setShowAll} label="Show every category" />
      </div>
    </Panel>
  );
}
