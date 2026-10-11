import { useMutation, useQuery } from "@tanstack/react-query";
import { Chess } from "chess.js";
import { Brain, Flag, Microscope, RotateCcw, Save, Swords, Undo2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { Badge, Button, Callout, ConfirmDialog, Field, IconButton, Panel, PanelHeader, Segmented, Spinner, Toggle } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { gameStatus, tryMove } from "@/lib/chess";
import { describeEval, formatEval } from "@/lib/eval";
import { fromMoves, START_FEN, toPgn } from "@/lib/tree";
import { useAnalysisStore } from "@/stores/analysis";
import { toast } from "@/stores/toast";
import type { AnalysisSnapshot, EngineId } from "@/types/api";
import { ChessBoard, type BoardMove } from "../board/ChessBoard";
import { EvalBar } from "../board/EvalBar";

function replay(list: { uci: string }[]): Chess {
  const c = new Chess();
  for (const m of list) c.move({ from: m.uci.slice(0, 2), to: m.uci.slice(2, 4), promotion: m.uci[4] });
  return c;
}

function statusOf(list: { uci: string }[]) {
  return gameStatus(replay(list));
}

interface PlayedMove {
  san: string;
  uci: string;
  fen: string;
}

type Side = "w" | "b";

interface GameSetup {
  engine: EngineId;
  level: number;
  userColor: Side;
}

export default function PlayPage() {
  const engines = useQuery({ queryKey: ["engines"], queryFn: api.engines });
  const levels = useQuery({ queryKey: ["levels"], queryFn: api.levels });
  const navigate = useNavigate();
  const loadAnalysis = useAnalysisStore((s) => s.load);

  const [setup, setSetup] = useState<GameSetup | null>(null);
  const [draft, setDraft] = useState<{ engine: EngineId | null; level: number; color: "w" | "b" | "random" }>({ engine: null, level: 4, color: "w" });
  const [moves, setMoves] = useState<PlayedMove[]>([]);
  const [thinking, setThinking] = useState(false);
  const [engineError, setEngineError] = useState<string | null>(null);
  const [lastEngine, setLastEngine] = useState<AnalysisSnapshot | null>(null);
  const [showThinking, setShowThinking] = useState(false);
  const [resigned, setResigned] = useState(false);
  const [confirmResign, setConfirmResign] = useState(false);
  const [saved, setSaved] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const available = engines.data?.filter((e) => e.available) ?? [];
  const draftEngine = draft.engine ?? available[0]?.id ?? null;

  const fen = moves.at(-1)?.fen ?? START_FEN;
  const chess = useMemo(() => replay(moves), [moves]);
  const status = gameStatus(chess);
  const over = status.over || resigned;
  const turn = chess.turn();
  const userTurn = setup !== null && turn === setup.userColor && !over;
  const result = resigned ? (setup?.userColor === "w" ? "0-1" : "1-0") : status.result;

  useEffect(() => () => abortRef.current?.abort(), []);

  /** Ask the engine to reply to `history`. Called from event handlers only. */
  const requestEngineMove = (history: PlayedMove[], game: GameSetup) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setThinking(true);
    setEngineError(null);
    const currentFen = history.at(-1)?.fen ?? START_FEN;
    api
      .bestMove({ moves: history.map((m) => m.uci), engine: game.engine, level: game.level }, controller.signal)
      .then((snap) => {
        if (controller.signal.aborted) return;
        const best = snap.best_move;
        const reply = best ? tryMove(currentFen, best.slice(0, 2), best.slice(2, 4), best[4]) : null;
        if (!reply) throw new Error("The engine did not return a legal move.");
        setLastEngine(snap);
        setMoves([...history, reply]);
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setEngineError(errorMessage(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setThinking(false);
      });
  };

  const start = () => {
    if (!draftEngine) return;
    const userColor: Side = draft.color === "random" ? (Math.random() < 0.5 ? "w" : "b") : draft.color;
    const game: GameSetup = { engine: draftEngine, level: draft.level, userColor };
    abortRef.current?.abort();
    setSetup(game);
    setMoves([]);
    setResigned(false);
    setSaved(false);
    setLastEngine(null);
    setEngineError(null);
    setThinking(false);
    if (userColor === "b") requestEngineMove([], game);
  };

  const onMove = (move: BoardMove) => {
    if (!userTurn || !setup) return false;
    const played = tryMove(fen, move.from, move.to, move.promotion);
    if (!played) return false;
    const next = [...moves, played];
    setMoves(next);
    if (!statusOf(next).over) requestEngineMove(next, setup);
    return true;
  };

  const takeback = () => {
    if (!setup) return;
    abortRef.current?.abort();
    setThinking(false);
    setEngineError(null);
    // Pop moves until it is the user's turn again (games start from the standard position).
    const sideToMove = (list: PlayedMove[]): Side => (list.length % 2 === 0 ? "w" : "b");
    let next = moves.slice(0, -1);
    while (next.length && sideToMove(next) !== setup.userColor) next = next.slice(0, -1);
    setMoves(next);
    if (sideToMove(next) !== setup.userColor) requestEngineMove(next, setup); // user is Black at move 0
  };

  const engineName = setup ? (setup.engine === "stockfish" ? "Stockfish" : "ChessLab Engine") : "";
  const levelLabel = setup ? levels.data?.[setup.engine]?.find((l) => l.level === setup.level)?.label : "";
  const headers: Record<string, string> = setup
    ? {
        Event: "ChessLab game",
        White: setup.userColor === "w" ? "You" : `${engineName} (${levelLabel ?? `level ${setup.level}`})`,
        Black: setup.userColor === "b" ? "You" : `${engineName} (${levelLabel ?? `level ${setup.level}`})`,
        Result: over ? (result ?? "*") : "*",
        ...(resigned ? { Termination: "You resigned" } : status.reason ? { Termination: status.reason } : {}),
      }
    : {};
  const tree = fromMoves(START_FEN, moves.map((m) => m.uci), headers);

  const save = useMutation({
    mutationFn: () => api.saveGame(toPgn(tree), "You"),
    onSuccess: (summary) => {
      setSaved(true);
      toast.success("Game saved to your library", summary.game_ids[0] ? "Open Game History to review it." : undefined);
    },
  });

  const analyse = () => {
    const ids = Object.keys(tree.nodes);
    loadAnalysis(tree, ids[ids.length - 1], setup?.userColor === "b" ? "black" : "white");
    navigate("/analysis");
  };

  const engineEval = lastEngine?.lines[0]?.score ?? null;
  const lastMove = moves.at(-1) ? { from: moves.at(-1)!.uci.slice(0, 2), to: moves.at(-1)!.uci.slice(2, 4) } : null;

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div className="min-w-0">
        <div className="mx-auto max-w-[min(100%,calc(100dvh-150px))] space-y-3">
          <PlayerStrip name={setup ? (setup.userColor === "w" ? engineName : "You") : "Opponent"} active={Boolean(setup) && !over && turn !== setup?.userColor} thinking={thinking} />
          <div className="flex gap-3">
            {showThinking && setup && <EvalBar evaluation={engineEval} turn="w" orientation={setup.userColor === "b" ? "black" : "white"} className="w-4 shrink-0 sm:w-6" />}
            <div className="min-w-0 flex-1">
            <ChessBoard
              id="play-board"
              fen={fen}
              orientation={setup?.userColor === "b" ? "black" : "white"}
              onMove={onMove}
              movable={setup && !over ? setup.userColor : "none"}
              lastMove={lastMove}
              ariaLabel="Game board"
            />
            </div>
          </div>
          <PlayerStrip name="You" active={userTurn} />
        </div>
      </div>

      <div className="space-y-4">
        {!setup || over ? (
          <Panel>
            <PanelHeader title={setup ? "Play again" : "New game"} icon={<Swords className="size-4" />} />
            <div className="space-y-4 p-4">
              <Field label="Opponent">
                <Segmented
                  label="Engine"
                  value={draftEngine ?? "stockfish"}
                  onChange={(v) => setDraft((d) => ({ ...d, engine: v as EngineId, level: v === "custom" ? 2 : 4 }))}
                  options={(engines.data ?? []).map((e) => ({ value: e.id, label: e.display_name, disabled: !e.available }))}
                />
              </Field>
              <Field label="Strength" hint={draftEngine === "stockfish" ? "Elo-based levels use Stockfish's own calibration, not a Chess.com or FIDE rating." : "The ChessLab engine is weaker: levels set its search depth and time."}>
                <select className="field" value={draft.level} onChange={(e) => setDraft((d) => ({ ...d, level: Number(e.target.value) }))}>
                  {(draftEngine ? levels.data?.[draftEngine] : [])?.map((l) => (
                    <option key={l.level} value={l.level}>
                      {l.level}. {l.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Your colour">
                <Segmented
                  label="Colour"
                  value={draft.color}
                  onChange={(v) => setDraft((d) => ({ ...d, color: v }))}
                  options={[
                    { value: "w", label: "White" },
                    { value: "random", label: "Random" },
                    { value: "b", label: "Black" },
                  ]}
                />
              </Field>
              <Button variant="primary" size="lg" className="w-full" onClick={start} disabled={!draftEngine} icon={<Swords className="size-4" />}>
                Start game
              </Button>
              {engines.data && !available.length && <Callout tone="warn">No engine is available. See Settings → Engines.</Callout>}
              <p className="text-xs text-ink-400">Games are untimed. Your game can be saved to your local library and reviewed afterwards.</p>
            </div>
          </Panel>
        ) : (
          <Panel>
            <PanelHeader
              title={`vs ${engineName}`}
              subtitle={levelLabel ?? undefined}
              actions={
                <>
                  <IconButton label="Take back" onClick={takeback} disabled={moves.length === 0 || (thinking && moves.length < 2)}>
                    <Undo2 className="size-4" />
                  </IconButton>
                  <Button size="sm" variant="danger" icon={<Flag className="size-3.5" />} onClick={() => setConfirmResign(true)}>
                    Resign
                  </Button>
                </>
              }
            />
            <div className="space-y-3 p-4">
              <p className="text-sm text-ink-200">
                {thinking ? (
                  <span className="inline-flex items-center gap-2">
                    <Spinner /> {engineName} is thinking…
                  </span>
                ) : userTurn ? (
                  "Your move."
                ) : (
                  "Waiting…"
                )}
              </p>
              {status.check && <Badge tone="bad">Check</Badge>}
              {engineError && (
                <Callout tone="bad" title="The engine could not move">
                  {engineError}
                  <div className="mt-2">
                    <Button size="sm" onClick={() => requestEngineMove(moves, setup)}>
                      Try again
                    </Button>
                  </div>
                </Callout>
              )}
            </div>
          </Panel>
        )}

        {over && setup && (
          <Panel>
            <div className="space-y-3 p-4">
              <p className="text-lg font-semibold text-ink-50">
                {result === "1/2-1/2" ? "Draw" : (result === "1-0") === (setup.userColor === "w") ? "You won" : "You lost"}
                <span className="num ml-2 text-sm text-ink-300">{result}</span>
              </p>
              <p className="text-sm text-ink-300">{resigned ? "You resigned." : `By ${status.reason}.`}</p>
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" icon={<Microscope className="size-4" />} onClick={analyse}>
                  Analyse this game
                </Button>
                <Button icon={<Save className="size-4" />} onClick={() => save.mutate()} loading={save.isPending} disabled={saved}>
                  {saved ? "Saved" : "Save to library"}
                </Button>
                <Button variant="ghost" icon={<RotateCcw className="size-4" />} onClick={start}>
                  Rematch
                </Button>
              </div>
            </div>
          </Panel>
        )}

        {setup && (
          <Panel>
            <PanelHeader title="Engine's reasoning" icon={<Brain className="size-4" />} />
            <div className="space-y-3 p-4">
              <Toggle checked={showThinking} onChange={setShowThinking} label="Show the engine's evaluation and plan" description="Hidden by default so it does not spoil the game." />
              {showThinking && lastEngine && lastEngine.lines[0] ? (
                <div className="space-y-2 rounded-lg border border-ink-700 bg-ink-900 p-3 text-sm">
                  <p>
                    Played <span className="num font-semibold text-ink-50">{lastEngine.best_move_san}</span>, evaluating the position at{" "}
                    <span className="num text-ink-50">{formatEval(lastEngine.lines[0].score)}</span> ({describeEval(lastEngine.lines[0].score)}) after a depth-{lastEngine.depth} search.
                  </p>
                  <p className="num text-xs text-ink-300">Expected continuation: {lastEngine.lines[0].pv_san.slice(0, 8).join(" ")}</p>
                  {setup.engine === "stockfish" && setup.level <= 8 && (
                    <p className="text-xs text-ink-400">At reduced strength Stockfish deliberately sometimes picks a weaker move than its search found best, so the plan shown may differ from the move played.</p>
                  )}
                </div>
              ) : showThinking ? (
                <p className="text-xs text-ink-400">The engine has not moved yet.</p>
              ) : null}
            </div>
          </Panel>
        )}

        {moves.length > 0 && (
          <Panel>
            <PanelHeader title="Moves" />
            <ol className="num grid max-h-60 grid-cols-[auto_1fr_1fr] gap-x-3 gap-y-0.5 overflow-y-auto p-3 text-sm">
              {Array.from({ length: Math.ceil(moves.length / 2) }, (_, i) => (
                <li key={i} className="contents">
                  <span className="text-ink-400">{i + 1}.</span>
                  <span className="text-ink-100">{moves[2 * i]?.san}</span>
                  <span className="text-ink-100">{moves[2 * i + 1]?.san ?? ""}</span>
                </li>
              ))}
            </ol>
          </Panel>
        )}
      </div>

      <ConfirmDialog
        open={confirmResign}
        title="Resign this game?"
        message="The game will end as a loss. You can still analyse or save it."
        confirmLabel="Resign"
        danger
        onCancel={() => setConfirmResign(false)}
        onConfirm={() => {
          abortRef.current?.abort();
          setThinking(false);
          setResigned(true);
          setConfirmResign(false);
        }}
      />
    </div>
  );
}

function PlayerStrip({ name, active, thinking }: { name: string; active: boolean; thinking?: boolean }) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-ink-700 bg-ink-850 px-3 py-1.5">
      <span className="text-sm font-medium text-ink-100">{name}</span>
      {thinking ? <Spinner /> : active ? <span className="size-2 rounded-full bg-brass-400" aria-label="To move" /> : null}
    </div>
  );
}
