// Evaluation display helpers. Scores are always from White's point of view;
// the expected-score curve matches the backend (app/services/chess/scoring.py).

import type { Evaluation, MoveClass } from "@/types/api";

const LOGISTIC_K = 0.00368208;

/** Expected score for White (0..1). `turn` is needed only for `mate === 0`. */
export function whiteExpectedScore(ev: Evaluation | null | undefined, turn: "w" | "b" = "w"): number {
  if (!ev) return 0.5;
  if (ev.mate !== null && ev.mate !== undefined) {
    if (ev.mate > 0) return 1;
    if (ev.mate < 0) return 0;
    return turn === "w" ? 0 : 1; // side to move is checkmated
  }
  return 1 / (1 + Math.exp(-LOGISTIC_K * (ev.cp ?? 0)));
}

/** "+0.32", "-1.50", "M3", "-M2", "#" (checkmate on the board). */
export function formatEval(ev: Evaluation | null | undefined, turn: "w" | "b" = "w"): string {
  if (!ev) return "–";
  if (ev.mate !== null && ev.mate !== undefined) {
    if (ev.mate === 0) return turn === "w" ? "0-1" : "1-0";
    return ev.mate > 0 ? `M${ev.mate}` : `-M${Math.abs(ev.mate)}`;
  }
  const pawns = (ev.cp ?? 0) / 100;
  if (Math.abs(pawns) < 0.005) return "0.00";
  return `${pawns > 0 ? "+" : ""}${pawns.toFixed(2)}`;
}

/** Plain-language reading of an evaluation (always hedged: it's an estimate). */
export function describeEval(ev: Evaluation | null | undefined, turn: "w" | "b" = "w"): string {
  if (!ev) return "No evaluation yet";
  if (ev.mate !== null && ev.mate !== undefined) {
    if (ev.mate === 0) return "Checkmate";
    const side = ev.mate > 0 ? "White" : "Black";
    return `${side} has a forced mate in ${Math.abs(ev.mate)}`;
  }
  const cp = ev.cp ?? 0;
  const abs = Math.abs(cp);
  const side = cp > 0 ? "White" : "Black";
  if (abs < 30) return "Roughly equal";
  if (abs < 90) return `${side} is slightly better`;
  if (abs < 200) return `${side} is clearly better`;
  if (abs < 500) return `${side} is winning`;
  void turn;
  return `${side} is completely winning`;
}

/** Clamp an evaluation for graphs: centipawns in [-1000, 1000], mates at the edge. */
export function graphValue(ev: Evaluation | null | undefined, turn: "w" | "b" = "w"): number {
  if (!ev) return 0;
  if (ev.mate !== null && ev.mate !== undefined) {
    if (ev.mate === 0) return turn === "w" ? -1000 : 1000;
    return ev.mate > 0 ? 1000 : -1000;
  }
  return Math.max(-1000, Math.min(1000, ev.cp ?? 0));
}

export const MOVE_CLASS_META: Record<MoveClass, { label: string; symbol: string; color: string; description: string }> = {
  best: { label: "Best", symbol: "★", color: "var(--color-q-best)", description: "The engine's top choice." },
  excellent: { label: "Excellent", symbol: "!", color: "var(--color-q-excellent)", description: "Almost no loss compared with the best move." },
  good: { label: "Good", symbol: "✓", color: "var(--color-q-good)", description: "A small, usually harmless loss." },
  inaccuracy: { label: "Inaccuracy", symbol: "?!", color: "var(--color-q-inaccuracy)", description: "A noticeable loss of winning chances." },
  mistake: { label: "Mistake", symbol: "?", color: "var(--color-q-mistake)", description: "A significant loss of winning chances." },
  blunder: { label: "Blunder", symbol: "??", color: "var(--color-q-blunder)", description: "A severe loss that can decide the game." },
  forced: { label: "Forced", symbol: "□", color: "var(--color-q-forced)", description: "The only legal move." },
};

export const MOVE_CLASS_ORDER: MoveClass[] = ["best", "excellent", "good", "inaccuracy", "mistake", "blunder", "forced"];
