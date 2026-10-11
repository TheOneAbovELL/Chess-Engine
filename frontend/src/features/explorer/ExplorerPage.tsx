import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { BookOpenText, Microscope, RotateCcw, Undo2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";
import { Button, Callout, EmptyState, IconButton, PageHeader, Panel, PanelHeader, Segmented, Skeleton, WdlBar } from "@/components/ui";
import { api, errorMessage, type GameQuery } from "@/lib/api";
import { tryMove, turnOf } from "@/lib/chess";
import { cn } from "@/lib/cn";
import { formatDate, formatPercent, SOURCE_LABEL, TIME_CLASS_LABEL } from "@/lib/format";
import { fromMoves, START_FEN } from "@/lib/tree";
import { useAnalysisStore } from "@/stores/analysis";
import { ChessBoard, type BoardMove } from "../board/ChessBoard";

interface Step {
  uci: string;
  san: string;
  fen: string;
}

export default function ExplorerPage() {
  const [path, setPath] = useState<Step[]>([]);
  const [color, setColor] = useState<"" | "white" | "black">("white");
  const [timeClass, setTimeClass] = useState("");
  const [owner, setOwner] = useState("");
  const navigate = useNavigate();
  const loadAnalysis = useAnalysisStore((s) => s.load);
  const owners = useQuery({ queryKey: ["owners"], queryFn: api.owners });

  const filters: GameQuery = useMemo(() => ({ color: color || undefined, time_class: timeClass || undefined, owner: owner || undefined }), [color, timeClass, owner]);
  const moves = path.map((p) => p.uci);
  const fen = path.at(-1)?.fen ?? START_FEN;
  const explorer = useQuery({ queryKey: ["explorer", moves, filters], queryFn: () => api.explorer(moves, filters), placeholderData: keepPreviousData });

  const userToMove = color ? (turnOf(fen) === "w") === (color === "white") : null;
  const play = (uci: string) => {
    const step = tryMove(fen, uci.slice(0, 2), uci.slice(2, 4), uci[4]);
    if (step) setPath((p) => [...p, step]);
  };
  const onBoardMove = (m: BoardMove) => {
    const step = tryMove(fen, m.from, m.to, m.promotion);
    if (!step) return false;
    setPath((p) => [...p, step]);
    return true;
  };
  const maxPly = explorer.data?.max_ply ?? 30;

  return (
    <div>
      <PageHeader
        title="Opening Explorer"
        description="Your own repertoire: the moves played from each position in your stored games, with your results. Built locally from your history."
      />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_480px]">
        <div className="mx-auto w-full max-w-[min(100%,calc(100dvh-200px))] space-y-3">
          <ChessBoard id="explorer-board" fen={fen} orientation={color === "black" ? "black" : "white"} onMove={path.length < maxPly ? onBoardMove : undefined} lastMove={path.at(-1) ? { from: path.at(-1)!.uci.slice(0, 2), to: path.at(-1)!.uci.slice(2, 4) } : null} ariaLabel="Explorer board" />
          <div className="flex flex-wrap items-center gap-2">
            <IconButton label="Back one move" onClick={() => setPath((p) => p.slice(0, -1))} disabled={!path.length}>
              <Undo2 className="size-4" />
            </IconButton>
            <IconButton label="Back to the start" onClick={() => setPath([])} disabled={!path.length}>
              <RotateCcw className="size-4" />
            </IconButton>
            <div className="num flex min-w-0 flex-1 flex-wrap gap-1 text-xs text-ink-300">
              {path.length === 0 && <span className="text-ink-500">Starting position</span>}
              {path.map((step, i) => (
                <button key={i} type="button" className="rounded px-1 hover:bg-ink-700 hover:text-ink-50" onClick={() => setPath((p) => p.slice(0, i + 1))}>
                  {i % 2 === 0 ? `${i / 2 + 1}.` : ""}
                  {step.san}
                </button>
              ))}
            </div>
            <Button
              size="sm"
              icon={<Microscope className="size-3.5" />}
              onClick={() => {
                const tree = fromMoves(START_FEN, moves);
                loadAnalysis(tree, `n${moves.length}`, color === "black" ? "black" : "white");
                navigate("/analysis");
              }}
            >
              Analyse
            </Button>
          </div>
        </div>

        <Panel>
          <PanelHeader title="Moves in this position" icon={<BookOpenText className="size-4" />} subtitle={explorer.data ? `${explorer.data.total_games.toLocaleString()} of your games reached it` : undefined} />
          <div className="flex flex-wrap items-center gap-2 border-b border-ink-700/70 px-4 py-2.5">
            <Segmented
              size="sm"
              label="Your colour"
              value={color}
              onChange={setColor}
              options={[
                { value: "white", label: "As White" },
                { value: "black", label: "As Black" },
                { value: "", label: "Both" },
              ]}
            />
            <select className="field h-8 w-auto py-0 text-xs" value={timeClass} onChange={(e) => setTimeClass(e.target.value)} aria-label="Time control">
              <option value="">All time controls</option>
              {Object.entries(TIME_CLASS_LABEL).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
            <select className="field h-8 w-auto py-0 text-xs" value={owner} onChange={(e) => setOwner(e.target.value)} aria-label="Account">
              <option value="">All accounts</option>
              {owners.data?.map((o) => (
                <option key={`${o.source}-${o.username}`} value={o.username}>
                  {o.username} · {SOURCE_LABEL[o.source]}
                </option>
              ))}
            </select>
          </div>
          {userToMove !== null && (
            <p className="border-b border-ink-700/70 px-4 py-2 text-xs text-ink-400">{userToMove ? "Your move here: what you chose." : "Opponent to move: what was played against you."}</p>
          )}
          {explorer.isError ? (
            <div className="p-4">
              <Callout tone="bad">{errorMessage(explorer.error)}</Callout>
            </div>
          ) : explorer.isPending ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 5 }, (_, i) => (
                <Skeleton key={i} className="h-8" />
              ))}
            </div>
          ) : explorer.data.moves.length === 0 ? (
            <EmptyState title={path.length ? "No games continue from here" : "No games yet"} actions={!path.length ? <Link to="/import"><Button variant="primary">Import games</Button></Link> : undefined}>
              {path.length >= maxPly ? `The explorer covers the first ${maxPly / 2} moves of each game.` : path.length ? "None of your stored games (with these filters) reached this position." : "Import games to build your personal opening tree."}
            </EmptyState>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-ink-400">
                  <th className="px-4 py-2 font-medium">Move</th>
                  <th className="px-2 py-2 text-right font-medium">Games</th>
                  <th className="w-[38%] px-3 py-2 font-medium">Your results</th>
                  <th className="px-3 py-2 text-right font-medium">Score</th>
                </tr>
              </thead>
              <tbody>
                {explorer.data.moves.map((m) => (
                  <tr key={m.uci} className="cursor-pointer border-t border-ink-800 hover:bg-ink-800/60" onClick={() => play(m.uci)}>
                    <td className="px-4 py-2">
                      <button type="button" className="num font-semibold text-ink-50 hover:text-brass-300" onClick={(e) => (e.stopPropagation(), play(m.uci))}>
                        {m.san}
                      </button>
                      {m.last_played && <p className="text-[10px] text-ink-500">last {formatDate(m.last_played)}</p>}
                    </td>
                    <td className="num px-2 py-2 text-right text-ink-300">
                      {m.games}
                      <span className="block text-[10px] text-ink-500">{formatPercent(m.share)}</span>
                    </td>
                    <td className="px-3 py-2">
                      <WdlBar wins={m.wins} draws={m.draws} losses={m.losses} />
                      <p className="num mt-1 text-[10px] text-ink-500">
                        {m.wins}W {m.draws}D {m.losses}L
                      </p>
                    </td>
                    <td className={cn("num px-3 py-2 text-right", (m.score ?? 0.5) >= 0.5 ? "text-q-best" : "text-[#ff8f88]")}>{formatPercent(m.score)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="border-t border-ink-700/70 px-4 py-2 text-[11px] text-ink-500">
            Transpositions are merged. Only games starting from the standard position, first {maxPly / 2} moves. Small samples are noisy.
          </p>
        </Panel>
      </div>
    </div>
  );
}
