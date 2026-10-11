import { useMutation, useQuery } from "@tanstack/react-query";
import { Chess } from "chess.js";
import {
  ArrowUpToLine,
  ClipboardCopy,
  Cpu,
  Download,
  FilePlus2,
  FileUp,
  Pause,
  Play,
  Redo2,
  RotateCcw,
  Trash2,
  Undo2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Callout, Dialog, Field, IconButton, Panel, PanelHeader, Segmented } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { gameStatus, tryMove, turnOf, validateFen } from "@/lib/chess";
import { describeEval } from "@/lib/eval";
import { deleteSubtree, fromServerNodes, getNode, isOnMainline, movesTo, promoteVariation, toPgn } from "@/lib/tree";
import { useLiveAnalysis } from "@/hooks/useLiveAnalysis";
import { useAnalysisStore } from "@/stores/analysis";
import { usePreferences } from "@/stores/preferences";
import { toast } from "@/stores/toast";
import type { EngineId } from "@/types/api";
import { BoardNav, MoveInput, useBoardKeys } from "../board/BoardControls";
import { ChessBoard, type BoardMove } from "../board/ChessBoard";
import { EvalBar } from "../board/EvalBar";
import { MoveTree } from "../board/MoveTree";
import { EngineLines } from "./EngineLines";

const DEPTH_OPTIONS = [
  { value: "inf", label: "∞" },
  { value: "16", label: "16" },
  { value: "22", label: "22" },
  { value: "30", label: "30" },
] as const;

export function downloadText(filename: string, text: string, type = "application/x-chess-pgn") {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

async function copy(text: string, what: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(`${what} copied`);
  } catch {
    toast.error("Copy failed", "The browser blocked clipboard access.");
  }
}

export default function AnalysisPage() {
  const { tree, currentId, orientation, play, goTo, back, forward, first, last, flip, load, reset, setTree, lastVisited } = useAnalysisStore();
  const { autoAnalyze, showBestArrow, set: setPrefs } = usePreferences();
  const engines = useQuery({ queryKey: ["engines"], queryFn: api.engines });
  const engineSettings = useQuery({ queryKey: ["settings", "engine"], queryFn: api.engineSettings });
  const config = useQuery({ queryKey: ["config"], queryFn: api.config });
  const live = useLiveAnalysis();

  const [engine, setEngine] = useState<EngineId | null>(null);
  const [multipv, setMultipv] = useState<number | null>(null);
  const [depth, setDepth] = useState<string>("inf");
  const [pgnOpen, setPgnOpen] = useState(false);
  const [fenOpen, setFenOpen] = useState(false);

  const node = getNode(tree, currentId);
  const fen = node.fen;
  const rootFen = getNode(tree, tree.rootId).fen;
  const history = useMemo(() => movesTo(tree, currentId), [tree, currentId]);
  const available = engines.data?.filter((e) => e.available) ?? [];
  const activeEngine: EngineId | undefined = engine ?? engineSettings.data?.default_engine ?? available[0]?.id;
  const activeMultipv = multipv ?? engineSettings.data?.analysis_multipv ?? 3;
  const maxMultipv = config.data?.limits.max_multipv ?? 5;

  const status = useMemo(() => {
    const chess = new Chess(rootFen);
    for (const uci of history) chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
    return gameStatus(chess);
  }, [rootFen, history]);

  // Re-analyse whenever the position or engine options change.
  useEffect(() => {
    if (!autoAnalyze || !activeEngine) {
      live.stop();
      return;
    }
    const timer = window.setTimeout(() => {
      live.start({ fen: rootFen, moves: history, engine: activeEngine, multipv: activeMultipv, depth: depth === "inf" ? null : Number(depth) });
    }, 120);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- live.start/stop are stable
  }, [autoAnalyze, activeEngine, activeMultipv, depth, rootFen, history.join(" ")]);

  const snapshot = live.snapshot && live.snapshot.fen === fen ? live.snapshot : null;
  const evaluation = snapshot?.lines[0]?.score ?? null;
  const bestArrow =
    showBestArrow && snapshot?.lines[0]?.pv[0]
      ? [{ from: snapshot.lines[0].pv[0].slice(0, 2), to: snapshot.lines[0].pv[0].slice(2, 4), color: "rgba(127,178,255,0.85)" }]
      : [];

  const onMove = (move: BoardMove) => {
    const result = tryMove(fen, move.from, move.to, move.promotion);
    if (!result) return false;
    play(result);
    return true;
  };

  const playUciLine = (ucis: string[]) => {
    let currentFen = fen;
    for (const uci of ucis) {
      const result = tryMove(currentFen, uci.slice(0, 2), uci.slice(2, 4), uci[4]);
      if (!result) break;
      useAnalysisStore.getState().play(result);
      currentFen = result.fen;
    }
  };

  useBoardKeys({ prev: back, next: forward, first, last, flip });

  const canRedo = Boolean(lastVisited[currentId] && node.children.includes(lastVisited[currentId]!));
  const pgn = useMemo(() => toPgn(tree), [tree]);
  const lastMove = node.uci ? { from: node.uci.slice(0, 2), to: node.uci.slice(2, 4) } : null;
  const turn = turnOf(fen);

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
      {/* Board column */}
      <div className="min-w-0">
        <div className="mx-auto max-w-[min(100%,calc(100dvh-140px))] space-y-3">
          <div className="flex gap-3">
            <EvalBar evaluation={evaluation} turn={turn} orientation={orientation} className="w-4 shrink-0 sm:w-6" />
            <div className="min-w-0 flex-1">
              <ChessBoard id="analysis-board" fen={fen} orientation={orientation} onMove={onMove} lastMove={lastMove} arrows={bestArrow} ariaLabel="Analysis board" />
            </div>
          </div>
          <div className="space-y-3 pl-7 sm:pl-9">
            <BoardNav
              onFirst={first}
              onPrev={back}
              onNext={forward}
              onLast={last}
              onFlip={flip}
              canBack={Boolean(node.parent)}
              canForward={node.children.length > 0}
            >
              <IconButton label="Undo (back)" onClick={back} disabled={!node.parent}>
                <Undo2 className="size-4" />
              </IconButton>
              <IconButton label="Redo" onClick={forward} disabled={!canRedo}>
                <Redo2 className="size-4" />
              </IconButton>
            </BoardNav>
            <MoveInput fen={fen} disabled={status.over} onMove={(uci) => onMove({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] as BoardMove["promotion"] })} />
          </div>
        </div>
      </div>

      {/* Side column */}
      <div className="min-w-0 space-y-4">
        <Panel>
          <PanelHeader
            title="Engine"
            icon={<Cpu className="size-4" />}
            subtitle={evaluation ? describeEval(evaluation, turn) : autoAnalyze ? "Analysing…" : "Paused"}
            actions={
              <Button
                size="sm"
                variant={autoAnalyze ? "secondary" : "primary"}
                icon={autoAnalyze ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
                onClick={() => setPrefs({ autoAnalyze: !autoAnalyze })}
                disabled={!activeEngine}
              >
                {autoAnalyze ? "Stop" : "Analyse"}
              </Button>
            }
          />
          <div className="flex flex-wrap items-center gap-2 border-b border-ink-700/70 px-4 py-2.5">
            <label className="sr-only" htmlFor="engine-select">
              Engine
            </label>
            <select
              id="engine-select"
              className="field h-8 w-auto py-0 text-xs"
              value={activeEngine ?? ""}
              onChange={(e) => setEngine(e.target.value as EngineId)}
              disabled={!available.length}
            >
              {engines.data?.map((e) => (
                <option key={e.id} value={e.id} disabled={!e.available}>
                  {e.display_name}
                  {e.available ? "" : " (not installed)"}
                </option>
              ))}
            </select>
            <Segmented
              size="sm"
              label="Candidate lines"
              value={String(activeMultipv)}
              onChange={(v) => setMultipv(Number(v))}
              options={Array.from({ length: maxMultipv }, (_, i) => ({ value: String(i + 1), label: String(i + 1) }))}
            />
            <Segmented size="sm" label="Depth limit" value={depth} onChange={setDepth} options={DEPTH_OPTIONS.map((o) => ({ ...o }))} />
          </div>
          {live.error && (
            <div className="px-4 pt-3">
              <Callout tone="bad" title="Analysis error">
                {live.error}
              </Callout>
            </div>
          )}
          {live.status === "offline" && (
            <div className="px-4 pt-3">
              <Callout tone="warn" title="Reconnecting to the engine server…" />
            </div>
          )}
          {engines.data && !available.length && (
            <div className="px-4 pt-3">
              <Callout tone="warn" title="No engine available">
                Install Stockfish (see Settings → Engines) or the ChessLab engine package.
              </Callout>
            </div>
          )}
          <EngineLines snapshot={snapshot} fen={fen} running={autoAnalyze && !status.over} onPlayLine={playUciLine} />
          <p className="border-t border-ink-700/70 px-4 py-2 text-[11px] leading-relaxed text-ink-400">
            Evaluations are engine estimates from White's point of view (+ favours White), not guaranteed outcomes. Infinite analysis stops
            automatically after {config.data?.limits.max_live_analysis_seconds ?? 180}s.
          </p>
        </Panel>

        {status.over && (
          <Callout tone="info" title={status.reason === "checkmate" ? `Checkmate · ${status.result}` : `Draw · ${status.reason}`}>
            The game has ended in this position.
          </Callout>
        )}

        <Panel>
          <PanelHeader
            title="Moves"
            subtitle={isOnMainline(tree, currentId) ? "Main line" : "Variation"}
            actions={
              node.parent ? (
                <>
                  {!isOnMainline(tree, currentId) && (
                    <IconButton label="Promote variation to main line" onClick={() => setTree(promoteVariation(tree, currentId))}>
                      <ArrowUpToLine className="size-4" />
                    </IconButton>
                  )}
                  <IconButton
                    label="Delete from this move"
                    onClick={() => {
                      const parent = node.parent!;
                      setTree(deleteSubtree(tree, currentId), parent);
                    }}
                  >
                    <Trash2 className="size-4" />
                  </IconButton>
                </>
              ) : null
            }
          />
          <div className="max-h-72 overflow-y-auto">
            <MoveTree tree={tree} currentId={currentId} onSelect={goTo} emptyHint="Drag or click pieces to explore. Variations are kept as branches." />
          </div>
        </Panel>

        <Panel>
          <PanelHeader title="Position" />
          <div className="space-y-3 p-4">
            <div className="flex items-center gap-2">
              <code className="num min-w-0 flex-1 truncate rounded-md bg-ink-900 px-2 py-1.5 text-[11px] text-ink-300" title={fen}>
                {fen}
              </code>
              <IconButton label="Copy FEN" onClick={() => copy(fen, "FEN")}>
                <ClipboardCopy className="size-4" />
              </IconButton>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" icon={<FileUp className="size-3.5" />} onClick={() => setPgnOpen(true)}>
                Load PGN
              </Button>
              <Button size="sm" icon={<FilePlus2 className="size-3.5" />} onClick={() => setFenOpen(true)}>
                Set up FEN
              </Button>
              <Button size="sm" icon={<Download className="size-3.5" />} onClick={() => downloadText("chesslab-analysis.pgn", pgn)}>
                Export PGN
              </Button>
              <Button size="sm" icon={<ClipboardCopy className="size-3.5" />} onClick={() => copy(pgn, "PGN")}>
                Copy PGN
              </Button>
              <Button size="sm" variant="ghost" icon={<RotateCcw className="size-3.5" />} onClick={() => reset()}>
                New board
              </Button>
            </div>
            <div className="flex flex-wrap gap-1.5">
              <Badge>{turn === "w" ? "White to move" : "Black to move"}</Badge>
              {status.check && !status.over && <Badge tone="bad">Check</Badge>}
            </div>
          </div>
        </Panel>
      </div>

      <LoadPgnDialog open={pgnOpen} onClose={() => setPgnOpen(false)} onLoaded={(t) => load(t)} />
      <SetupFenDialog
        open={fenOpen}
        onClose={() => setFenOpen(false)}
        onLoad={(f) => {
          reset(f);
          setFenOpen(false);
        }}
      />
    </div>
  );
}

function LoadPgnDialog({ open, onClose, onLoaded }: { open: boolean; onClose: () => void; onLoaded: (tree: ReturnType<typeof fromServerNodes>) => void }) {
  const [text, setText] = useState("");
  const parse = useMutation({
    mutationFn: (pgn: string) => api.parsePgn(pgn),
    onSuccess: (data) => {
      onLoaded(fromServerNodes(data.nodes, data.headers));
      toast.success("PGN loaded", data.games_in_text > 1 ? `Showing the first of ${data.games_in_text} games.` : undefined);
      setText("");
      onClose();
    },
    onError: () => undefined,
  });
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Load PGN"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={parse.isPending} disabled={!text.trim()} onClick={() => parse.mutate(text)}>
            Load
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <p>Paste a game. Variations and comments are kept; the server validates every move.</p>
        <textarea className="field num h-48 resize-y text-xs" value={text} onChange={(e) => setText(e.target.value)} placeholder={'[Event "?"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 *'} aria-label="PGN text" />
        <input
          type="file"
          accept=".pgn,text/plain"
          className="block text-xs text-ink-300 file:mr-3 file:rounded-md file:border-0 file:bg-ink-700 file:px-3 file:py-1.5 file:text-ink-100"
          onChange={async (e) => {
            const file = e.target.files?.[0];
            if (file) setText(await file.text());
          }}
          aria-label="Choose a PGN file"
        />
        {parse.isError && <Callout tone="bad">{errorMessage(parse.error)}</Callout>}
      </div>
    </Dialog>
  );
}

function SetupFenDialog({ open, onClose, onLoad }: { open: boolean; onClose: () => void; onLoad: (fen: string) => void }) {
  const [fen, setFen] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const submit = async () => {
    const local = validateFen(fen.trim());
    if (local) {
      setError(local);
      return;
    }
    setChecking(true);
    try {
      const info = await api.validate({ fen: fen.trim() }); // the backend's full legality check
      onLoad(info.fen);
      setFen("");
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setChecking(false);
    }
  };
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Set up a position"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={submit} loading={checking} disabled={!fen.trim()}>
            Load position
          </Button>
        </>
      }
    >
      <Field label="FEN" htmlFor="fen-input" error={error} hint="Example: r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3">
        <input id="fen-input" className="field num text-xs" value={fen} onChange={(e) => setFen(e.target.value)} spellCheck={false} />
      </Field>
    </Dialog>
  );
}
