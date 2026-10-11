import { Cpu } from "lucide-react";
import { cn } from "@/lib/cn";
import { formatEval } from "@/lib/eval";
import { formatCompact } from "@/lib/format";
import { turnOf } from "@/lib/chess";
import type { AnalysisSnapshot } from "@/types/api";

/** Candidate lines with evaluations. Clicking a move plays the line up to it. */
export function EngineLines({
  snapshot,
  fen,
  running,
  onPlayLine,
  maxMoves = 12,
}: {
  snapshot: AnalysisSnapshot | null;
  fen: string;
  running: boolean;
  onPlayLine?: (uciMoves: string[]) => void;
  maxMoves?: number;
}) {
  const turn = turnOf(fen);
  const startNumber = Number(fen.split(" ")[5] ?? "1") || 1;

  if (snapshot?.terminal) {
    return (
      <p className="px-4 py-3 text-sm text-ink-300">
        {snapshot.terminal === "checkmate" ? "Checkmate: the game is over." : `Game over (${snapshot.terminal.replace(/_/g, " ")}).`}
      </p>
    );
  }
  if (!snapshot || snapshot.lines.length === 0) {
    return (
      <div className="space-y-2 px-4 py-3">
        {running ? (
          <>
            <div className="skeleton h-5 w-full" />
            <div className="skeleton h-5 w-5/6" />
            <div className="skeleton h-5 w-4/6" />
          </>
        ) : (
          <p className="flex items-center gap-2 text-sm text-ink-400">
            <Cpu className="size-4" /> Engine idle.
          </p>
        )}
      </div>
    );
  }

  return (
    <div>
      <ol className="divide-y divide-ink-700/70">
        {snapshot.lines.map((line) => {
          const label = formatEval(line.score, turn);
          const positive = (line.score.mate ?? 0) > 0 || (line.score.mate === null && (line.score.cp ?? 0) >= 0);
          return (
            <li key={line.multipv} className="flex items-start gap-3 px-4 py-2">
              <span
                className={cn(
                  "num mt-0.5 w-14 shrink-0 rounded-md px-1.5 py-0.5 text-center text-xs font-semibold",
                  positive ? "bg-eval-white text-ink-900" : "bg-eval-black text-ink-50 ring-1 ring-ink-600",
                )}
                title={`Depth ${line.depth}`}
              >
                {label}
              </span>
              <div className="num min-w-0 flex-1 text-[13px] leading-6 text-ink-200">
                {line.pv_san.slice(0, maxMoves).map((san, i) => {
                  const ply = i + (turn === "b" ? 1 : 0);
                  const moveNumber = startNumber + Math.floor(ply / 2);
                  const showNumber = ply % 2 === 0 || i === 0;
                  return (
                    <button
                      key={`${line.multipv}-${i}`}
                      type="button"
                      className={cn("rounded px-0.5 hover:bg-ink-700 hover:text-ink-50", i === 0 && "font-semibold text-ink-50")}
                      onClick={() => onPlayLine?.(line.pv.slice(0, i + 1))}
                      title="Play this line up to here"
                    >
                      {showNumber && <span className="text-ink-400">{ply % 2 === 0 ? `${moveNumber}.` : `${moveNumber}...`}</span>}
                      {san}
                    </button>
                  );
                })}
                {line.pv_san.length > maxMoves && <span className="text-ink-500"> …</span>}
              </div>
            </li>
          );
        })}
      </ol>
      <div className="num flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-ink-700/70 px-4 py-2 text-[11px] text-ink-400">
        <span>
          depth <span className="text-ink-200">{snapshot.depth}</span>
          {snapshot.seldepth ? `/${snapshot.seldepth}` : ""}
        </span>
        <span>
          nodes <span className="text-ink-200">{formatCompact(snapshot.nodes)}</span>
        </span>
        <span>
          speed <span className="text-ink-200">{snapshot.nps ? `${formatCompact(snapshot.nps)}/s` : "–"}</span>
        </span>
        <span>
          time <span className="text-ink-200">{snapshot.time_ms !== null ? `${(snapshot.time_ms / 1000).toFixed(1)}s` : "–"}</span>
        </span>
        <span className="ml-auto truncate">{snapshot.engine_name}</span>
      </div>
    </div>
  );
}
