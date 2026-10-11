import { describeEval, formatEval, whiteExpectedScore } from "@/lib/eval";
import { cn } from "@/lib/cn";
import type { Evaluation } from "@/types/api";

/** Vertical evaluation bar. The white share is the expected score (same curve
 *  as the backend), so +1 pawn fills ~59% and a forced mate fills it all. */
export function EvalBar({ evaluation, turn = "w", orientation = "white", className }: { evaluation: Evaluation | null; turn?: "w" | "b"; orientation?: "white" | "black"; className?: string }) {
  const white = whiteExpectedScore(evaluation, turn);
  const pct = Math.round(white * 1000) / 10;
  const label = formatEval(evaluation, turn);
  const whiteAhead = white >= 0.5;
  const flipped = orientation === "black";
  return (
    <div
      className={cn("relative overflow-hidden rounded-md border border-ink-700 bg-eval-black", className ?? "w-4")}
      role="meter"
      aria-label={`Evaluation: ${describeEval(evaluation, turn)} (${label})`}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      title={`${label}: ${describeEval(evaluation, turn)}`}
    >
      <div
        className="absolute inset-x-0 bg-eval-white transition-[height] duration-500 ease-out"
        style={{ height: `${pct}%`, [flipped ? "top" : "bottom"]: 0 }}
      />
      <div className="absolute inset-x-0 top-1/2 h-px bg-brass-500/50" />
      <span
        className={cn(
          "num absolute inset-x-0 hidden text-center text-[9px] font-semibold tracking-tighter sm:block",
          whiteAhead !== flipped ? "bottom-1 text-ink-900" : "top-1 text-ink-100",
        )}
      >
        {evaluation ? label.replace(/^\+/, "") : ""}
      </span>
    </div>
  );
}
