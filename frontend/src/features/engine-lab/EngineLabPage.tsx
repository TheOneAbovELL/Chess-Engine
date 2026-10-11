import { useMutation, useQuery } from "@tanstack/react-query";
import { Cpu, FlaskConical, Gauge, Scale, Terminal } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Callout, Field, PageHeader, Panel, PanelHeader, Segmented, Skeleton } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { validateFen } from "@/lib/chess";
import { cn } from "@/lib/cn";
import { formatEval } from "@/lib/eval";
import { formatCompact, formatNumber } from "@/lib/format";
import { getNode, movesTo } from "@/lib/tree";
import { useAnalysisStore } from "@/stores/analysis";
import type { CompareResult, EngineDescriptor } from "@/types/api";
import { ChessBoard } from "../board/ChessBoard";

const TECHNIQUES = {
  Search: [
    "Negamax alpha-beta with principal-variation search",
    "Iterative deepening with a triangular PV table",
    "Quiescence search (captures, queen promotions, check evasions) with delta pruning",
    "Transposition table (Zobrist keys) with mate-score adjustment",
    "Move ordering: TT move, MVV-LVA, promotions, killer moves, history heuristic",
    "Null-move pruning, late-move reductions, check extension, mate-distance pruning",
    "MultiPV, time management, node limits and cooperative cancellation",
  ],
  Evaluation: [
    "Tapered PeSTO material + piece-square tables",
    "Mobility (excluding squares attacked by enemy pawns)",
    "King safety: pawn shield, open files, attacker pressure",
    "Pawn structure: doubled, isolated, connected (cached in a pawn hash)",
    "Passed pawns by rank",
    "Piece activity: bishop pair, rooks on open files and the 7th",
    "Endgame mop-up to convert won K+Q / K+R endings",
  ],
  "Not yet implemented": [
    "Own bitboard move generator (uses python-chess today)",
    "Incremental Zobrist hashing and incremental evaluation",
    "Static exchange evaluation, aspiration windows, futility pruning",
    "Tuned evaluation weights (e.g. Texel tuning), opening book, endgame tablebases",
  ],
};

export default function EngineLabPage() {
  const engines = useQuery({ queryKey: ["engines"], queryFn: api.engines, refetchInterval: 10_000 });
  const { tree, currentId } = useAnalysisStore();
  const analysisFen = getNode(tree, currentId).fen;
  const [source, setSource] = useState<"analysis" | "fen">("analysis");
  const [fenText, setFenText] = useState("");
  const [limitKind, setLimitKind] = useState<"depth" | "time">("depth");
  const [depth, setDepth] = useState(6);
  const [seconds, setSeconds] = useState(2);

  const fenError = source === "fen" && fenText.trim() ? validateFen(fenText.trim()) : null;
  const fen = source === "fen" && fenText.trim() && !fenError ? fenText.trim() : analysisFen;
  const payload = source === "analysis" ? { fen: getNode(tree, tree.rootId).fen, moves: movesTo(tree, currentId) } : { fen };

  const compare = useMutation({
    mutationFn: () =>
      api.compare({
        ...payload,
        engines: (engines.data ?? []).filter((e) => e.available).map((e) => e.id),
        ...(limitKind === "depth" ? { depth } : { movetime_ms: seconds * 1000 }),
      }),
  });
  const breakdown = useQuery({ queryKey: ["breakdown", fen], queryFn: () => api.evaluate(fen), enabled: !fenError });

  return (
    <div>
      <PageHeader
        title="Engine Lab"
        description="Compare Stockfish with ChessLab's own engine on the same position, and look inside the custom engine's evaluation."
      />

      <div className="mb-5 grid gap-4 md:grid-cols-2">
        {engines.isPending ? (
          <>
            <Skeleton className="h-28" />
            <Skeleton className="h-28" />
          </>
        ) : (
          engines.data?.map((e) => <EngineCard key={e.id} engine={e} />)
        )}
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,420px)_1fr]">
        <div className="space-y-4">
          <Panel>
            <PanelHeader title="Position" />
            <div className="space-y-3 p-4">
              <Segmented
                size="sm"
                label="Position source"
                value={source}
                onChange={setSource}
                options={[
                  { value: "analysis", label: "Current analysis position" },
                  { value: "fen", label: "Custom FEN" },
                ]}
              />
              {source === "fen" && (
                <Field label="FEN" error={fenError}>
                  <input className="field num text-xs" value={fenText} onChange={(e) => setFenText(e.target.value)} placeholder="Paste a FEN" spellCheck={false} />
                </Field>
              )}
              <ChessBoard id="lab-board" fen={fen} movable="none" ariaLabel="Position being compared" />
            </div>
          </Panel>
        </div>

        <div className="min-w-0 space-y-4">
          <Panel>
            <PanelHeader title="Head-to-head" icon={<Scale className="size-4" />} />
            <div className="space-y-4 p-4">
              <div className="flex flex-wrap items-end gap-3">
                <Field label="Limit">
                  <Segmented size="sm" label="Limit type" value={limitKind} onChange={setLimitKind} options={[{ value: "depth", label: "Same depth" }, { value: "time", label: "Same time" }]} />
                </Field>
                {limitKind === "depth" ? (
                  <Field label={`Depth: ${depth}`}>
                    <input type="range" min={1} max={8} value={depth} onChange={(e) => setDepth(Number(e.target.value))} className="w-40 accent-[var(--color-brass-500)]" aria-label="Depth" />
                  </Field>
                ) : (
                  <Field label={`Time: ${seconds}s each`}>
                    <input type="range" min={1} max={10} value={seconds} onChange={(e) => setSeconds(Number(e.target.value))} className="w-40 accent-[var(--color-brass-500)]" aria-label="Seconds per engine" />
                  </Field>
                )}
                <Button variant="primary" icon={<FlaskConical className="size-4" />} loading={compare.isPending} disabled={Boolean(fenError) || !engines.data?.some((e) => e.available)} onClick={() => compare.mutate()}>
                  Run comparison
                </Button>
              </div>
              <p className="text-xs text-ink-400">
                Engines run one after the other so they do not compete for CPU. The custom engine is pure Python and searches roughly 10,000 positions per second; above depth 6 it can take a long time on complex positions (searches are capped).
              </p>
              {compare.isError && <Callout tone="bad">{errorMessage(compare.error)}</Callout>}
              {compare.data && (
                <>
                  <div className="grid gap-3 lg:grid-cols-2">
                    {compare.data.map((r) => (
                      <CompareCard key={r.engine_id} result={r} fen={fen} />
                    ))}
                  </div>
                  <Callout tone="info" title="Reading the numbers">
                    Evaluation scales differ: Stockfish's centipawns come from a neural network calibrated to win probability, while the custom engine adds hand-written terms. A score of +1.0 from each does not mean the same thing. Compare move choices and lines rather than raw numbers, and note that “depth” is not equal effort across engines.
                  </Callout>
                </>
              )}
            </div>
          </Panel>

          <Panel>
            <PanelHeader title="Custom engine evaluation breakdown" icon={<Gauge className="size-4" />} subtitle="Static evaluation (no search), White's point of view, in centipawns" />
            <div className="p-4">
              {breakdown.isPending ? (
                <Skeleton className="h-40" />
              ) : breakdown.isError ? (
                <Callout tone="bad">{errorMessage(breakdown.error)}</Callout>
              ) : (
                <Breakdown data={breakdown.data.components} total={breakdown.data.total_white_pov} phase={breakdown.data.phase} maxPhase={breakdown.data.max_phase} />
              )}
            </div>
          </Panel>

          <Panel>
            <PanelHeader title="What the custom engine implements" icon={<Cpu className="size-4" />} />
            <div className="grid gap-4 p-4 md:grid-cols-3">
              {Object.entries(TECHNIQUES).map(([group, items]) => (
                <div key={group}>
                  <p className={cn("label mb-2", group === "Not yet implemented" && "text-q-inaccuracy")}>{group}</p>
                  <ul className="space-y-1.5 text-xs text-ink-300">
                    {items.map((t) => (
                      <li key={t} className="flex gap-1.5">
                        <span className={group === "Not yet implemented" ? "text-ink-500" : "text-q-best"}>{group === "Not yet implemented" ? "○" : "●"}</span>
                        {t}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </Panel>

          <Panel>
            <PanelHeader title="Benchmark and measure strength" icon={<Terminal className="size-4" />} subtitle="Run from a terminal in the repository folder (backend virtualenv)" />
            <div className="space-y-3 p-4 text-xs text-ink-300">
              <p>Fixed-depth benchmark (reproducible node counts; compare against the saved baseline):</p>
              <pre className="num overflow-x-auto rounded-lg bg-ink-900 p-3 text-ink-100">python engine-lab/benchmarks/bench.py --depth 4 --compare engine-lab/benchmarks/results/baseline.json</pre>
              <p>Controlled match with colours alternated (e.g. measure whether null-move pruning helps):</p>
              <pre className="num overflow-x-auto rounded-lg bg-ink-900 p-3 text-ink-100">python engine-lab/benchmarks/match.py --options2 UseNullMove=false --movetime 200</pre>
              <p>Match results report an Elo difference with a 95% confidence interval for that match only. ChessLab does not assign the engine an absolute Elo rating.</p>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}

function EngineCard({ engine }: { engine: EngineDescriptor }) {
  const tone = !engine.available ? "warn" : engine.status === "error" ? "bad" : engine.status === "busy" ? "info" : "good";
  return (
    <Panel className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-semibold text-ink-50">{engine.display_name}</p>
          <p className="text-xs text-ink-400">{engine.name ?? (engine.available ? "Starts on first use" : "Not installed")}</p>
        </div>
        <Badge tone={tone}>{engine.available ? engine.status : "unavailable"}</Badge>
      </div>
      {engine.detail && <p className="mt-2 text-xs text-q-inaccuracy">{engine.detail}</p>}
      <div className="mt-3 flex flex-wrap gap-1.5">
        {engine.capabilities.multipv && <span className="chip">MultiPV ≤ {engine.capabilities.max_multipv}</span>}
        {engine.capabilities.limit_strength && <span className="chip">Strength levels</span>}
        {engine.capabilities.threads && <span className="chip">Multi-threaded</span>}
        {engine.capabilities.eval_breakdown && <span className="chip">Eval breakdown</span>}
        <span className="chip">Depth / time / node limits</span>
      </div>
    </Panel>
  );
}

function CompareCard({ result, fen }: { result: CompareResult; fen: string }) {
  const snap = result.snapshot;
  const turn = fen.split(" ")[1] === "b" ? "b" : "w";
  return (
    <div className="rounded-xl border border-ink-700 bg-ink-900 p-4">
      <p className="text-sm font-semibold text-ink-50">{snap?.engine_name ?? (result.engine_id === "stockfish" ? "Stockfish" : "ChessLab Engine")}</p>
      {result.error || !snap ? (
        <p className="mt-2 text-xs text-[#ff8f88]">{result.error ?? "No result"}</p>
      ) : snap.terminal ? (
        <p className="mt-2 text-xs text-ink-300">Game over: {snap.terminal}</p>
      ) : (
        <>
          <div className="mt-3 flex items-baseline gap-3">
            <span className="num text-2xl font-semibold text-brass-300">{snap.best_move_san ?? "–"}</span>
            <span className="num text-sm text-ink-100">{formatEval(snap.lines[0]?.score, turn)}</span>
          </div>
          <dl className="num mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            <dt className="text-ink-400">Depth</dt>
            <dd className="text-ink-100">
              {snap.depth}
              {snap.seldepth ? ` / sel ${snap.seldepth}` : ""}
            </dd>
            <dt className="text-ink-400">Nodes</dt>
            <dd className="text-ink-100">{formatNumber(snap.nodes)}</dd>
            <dt className="text-ink-400">Speed</dt>
            <dd className="text-ink-100">{snap.nps ? `${formatCompact(snap.nps)} nodes/s` : "–"}</dd>
            <dt className="text-ink-400">Time</dt>
            <dd className="text-ink-100">{snap.time_ms !== null ? `${(snap.time_ms / 1000).toFixed(2)} s` : "–"}</dd>
          </dl>
          <p className="num mt-3 text-xs leading-relaxed text-ink-300">{snap.lines[0]?.pv_san.slice(0, 10).join(" ")}</p>
        </>
      )}
    </div>
  );
}

function Breakdown({ data, total, phase, maxPhase }: { data: Record<string, number>; total: number; phase: number; maxPhase: number }) {
  const entries = Object.entries(data);
  const max = Math.max(50, ...entries.map(([, v]) => Math.abs(v)));
  const label = (k: string) => k.replace(/_/g, " ").replace("pst", "+ piece-square");
  return (
    <div className="space-y-2">
      {entries.map(([key, value]) => (
        <div key={key} className="grid grid-cols-[150px_1fr_60px] items-center gap-3 text-xs">
          <span className="truncate capitalize text-ink-300">{label(key)}</span>
          <div className="relative h-3 rounded bg-ink-800">
            <div className="absolute inset-y-0 left-1/2 w-px bg-ink-600" />
            <div
              className={cn("absolute inset-y-0 rounded", value >= 0 ? "left-1/2 bg-eval-white/80" : "right-1/2 bg-q-blunder/70")}
              style={{ width: `${(Math.abs(value) / max) * 50}%` }}
            />
          </div>
          <span className="num text-right text-ink-100">{value > 0 ? `+${value}` : value}</span>
        </div>
      ))}
      <div className="flex items-center justify-between border-t border-ink-700/70 pt-2 text-xs">
        <span className="text-ink-400">
          Game phase {phase}/{maxPhase} ({phase >= 18 ? "middlegame" : phase <= 6 ? "endgame" : "transition"})
        </span>
        <span className="num font-semibold text-ink-50">Total {total > 0 ? `+${total}` : total} cp</span>
      </div>
    </div>
  );
}
