// Thin helpers around chess.js for the UI. The backend re-validates every
// position it receives; these exist so the board responds instantly.

import { Chess, type Square } from "chess.js";

export type Color = "w" | "b";

export interface GameStatus {
  over: boolean;
  check: boolean;
  result: "1-0" | "0-1" | "1/2-1/2" | null;
  reason: "checkmate" | "stalemate" | "threefold repetition" | "fifty-move rule" | "insufficient material" | null;
}

export function safeChess(fen: string): Chess | null {
  try {
    return new Chess(fen);
  } catch {
    return null;
  }
}

/** Status of a game given its full history (needed for repetition). */
export function gameStatus(chess: Chess): GameStatus {
  const check = chess.inCheck();
  if (chess.isCheckmate()) return { over: true, check, result: chess.turn() === "w" ? "0-1" : "1-0", reason: "checkmate" };
  if (chess.isStalemate()) return { over: true, check, result: "1/2-1/2", reason: "stalemate" };
  if (chess.isInsufficientMaterial()) return { over: true, check, result: "1/2-1/2", reason: "insufficient material" };
  if (chess.isThreefoldRepetition()) return { over: true, check, result: "1/2-1/2", reason: "threefold repetition" };
  if (chess.isDrawByFiftyMoves()) return { over: true, check, result: "1/2-1/2", reason: "fifty-move rule" };
  return { over: false, check, result: null, reason: null };
}

/** Legal destination squares for each origin square. */
export function legalTargets(fen: string): Map<string, string[]> {
  const chess = safeChess(fen);
  const map = new Map<string, string[]>();
  if (!chess) return map;
  for (const move of chess.moves({ verbose: true })) {
    const list = map.get(move.from) ?? [];
    if (!list.includes(move.to)) list.push(move.to);
    map.set(move.from, list);
  }
  return map;
}

export function isPromotion(fen: string, from: string, to: string): boolean {
  const chess = safeChess(fen);
  if (!chess) return false;
  return chess.moves({ square: from as Square, verbose: true }).some((m) => m.to === to && Boolean(m.promotion));
}

/** Try a move; returns SAN, UCI and resulting FEN, or null if illegal. */
export function tryMove(fen: string, from: string, to: string, promotion?: string): { san: string; uci: string; fen: string } | null {
  const chess = safeChess(fen);
  if (!chess) return null;
  try {
    const move = chess.move({ from, to, promotion });
    return { san: move.san, uci: `${move.from}${move.to}${move.promotion ?? ""}`, fen: chess.fen() };
  } catch {
    return null;
  }
}

/** Parse a typed move in SAN ("Nf3") or UCI ("g1f3"). */
export function parseTypedMove(fen: string, text: string): { san: string; uci: string; fen: string } | null {
  const chess = safeChess(fen);
  if (!chess) return null;
  const input = text.trim();
  if (!input) return null;
  try {
    const move = /^[a-h][1-8][a-h][1-8][qrbn]?$/i.test(input)
      ? chess.move({ from: input.slice(0, 2).toLowerCase(), to: input.slice(2, 4).toLowerCase(), promotion: input[4]?.toLowerCase() })
      : chess.move(input);
    return { san: move.san, uci: `${move.from}${move.to}${move.promotion ?? ""}`, fen: chess.fen() };
  } catch {
    return null;
  }
}

export function kingSquareInCheck(fen: string): string | null {
  const chess = safeChess(fen);
  if (!chess || !chess.inCheck()) return null;
  const turn = chess.turn();
  for (const row of chess.board()) {
    for (const piece of row) {
      if (piece && piece.type === "k" && piece.color === turn) return piece.square;
    }
  }
  return null;
}

export function turnOf(fen: string): Color {
  return fen.split(" ")[1] === "b" ? "b" : "w";
}

/** Convert a UCI PV into SAN from a FEN (stops at the first illegal move). */
export function uciLineToSan(fen: string, uciMoves: string[]): string[] {
  const chess = safeChess(fen);
  if (!chess) return [];
  const sans: string[] = [];
  for (const uci of uciMoves) {
    try {
      sans.push(chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] }).san);
    } catch {
      break;
    }
  }
  return sans;
}

export function validateFen(fen: string): string | null {
  try {
    new Chess(fen);
    return null;
  } catch (error) {
    return error instanceof Error ? error.message : "Invalid FEN";
  }
}

/** Move number label for a ply: ply 1 -> "1.", ply 2 -> "1...". */
export function moveLabel(plyAfterMove: number): string {
  const moverPly = plyAfterMove - 1;
  const number = Math.floor(moverPly / 2) + 1;
  return moverPly % 2 === 0 ? `${number}.` : `${number}...`;
}
