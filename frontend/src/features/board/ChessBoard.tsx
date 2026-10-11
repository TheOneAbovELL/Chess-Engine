// The interactive chessboard used across Play, Analysis, Review and Explorer.
//
// Rendering, drag & drop and animation come from react-chessboard. This
// wrapper adds what an analysis tool needs: click-to-move, legal-move hints,
// last-move / check / selection highlights, engine arrows, an accessible
// promotion picker, and strict legality (illegal drops snap back).

import { useMemo, useState, type CSSProperties } from "react";
import { Chessboard, defaultPieces } from "react-chessboard";
import { isPromotion, kingSquareInCheck, legalTargets, safeChess, turnOf } from "@/lib/chess";
import { BOARD_THEMES, usePreferences } from "@/stores/preferences";

export interface BoardArrow {
  from: string;
  to: string;
  color?: string;
}

export interface BoardMove {
  from: string;
  to: string;
  promotion?: "q" | "r" | "b" | "n";
}

interface ChessBoardProps {
  id: string;
  fen: string;
  orientation?: "white" | "black";
  /** Called with a legal move. Return false to reject it. */
  onMove?: (move: BoardMove) => boolean | void;
  /** Which side the user may move ("both" for analysis). */
  movable?: "w" | "b" | "both" | "none";
  lastMove?: { from: string; to: string } | null;
  arrows?: BoardArrow[];
  squareMarkers?: Record<string, CSSProperties>;
  ariaLabel?: string;
}

const PIECE_NAMES: Record<string, string> = { k: "king", q: "queen", r: "rook", b: "bishop", n: "knight", p: "pawn" };

/** "White to move. White: king e1, queen d1, … Black: …" for screen readers. */
function describePosition(fen: string): string {
  const chess = safeChess(fen);
  if (!chess) return "Invalid position.";
  const sides: Record<"w" | "b", string[]> = { w: [], b: [] };
  const order = "kqrbnp";
  const pieces = chess.board().flat().filter((p): p is NonNullable<typeof p> => p !== null);
  pieces.sort((a, b) => order.indexOf(a.type) - order.indexOf(b.type) || a.square.localeCompare(b.square));
  for (const piece of pieces) sides[piece.color].push(`${PIECE_NAMES[piece.type]} ${piece.square}`);
  const status = chess.isCheckmate() ? " Checkmate." : chess.inCheck() ? " Check." : "";
  return `${chess.turn() === "w" ? "White" : "Black"} to move.${status} White: ${sides.w.join(", ")}. Black: ${sides.b.join(", ")}.`;
}

const HIGHLIGHT_LAST = "rgba(214, 167, 86, 0.38)";
const HIGHLIGHT_SELECTED = "rgba(214, 167, 86, 0.55)";

export function ChessBoard({ id, fen, orientation = "white", onMove, movable = "both", lastMove, arrows = [], squareMarkers, ariaLabel }: ChessBoardProps) {
  const { boardTheme, showCoordinates, animations } = usePreferences();
  const theme = BOARD_THEMES[boardTheme];
  // Selection and pending promotion remember the position they belong to, so a
  // new position (navigation, engine reply) clears them without an effect.
  const [selection, setSelection] = useState<{ fen: string; square: string } | null>(null);
  const [promotion, setPromotion] = useState<{ fen: string; from: string; to: string } | null>(null);
  const selected = selection?.fen === fen ? selection.square : null;
  const pendingPromotion = promotion?.fen === fen ? promotion : null;
  const setSelected = (square: string | null) => setSelection(square ? { fen, square } : null);
  const setPendingPromotion = (p: { from: string; to: string } | null) => setPromotion(p ? { fen, ...p } : null);

  const targets = useMemo(() => legalTargets(fen), [fen]);
  const turn = turnOf(fen);
  const canMoveNow = movable === "both" || movable === turn;
  const checkSquare = useMemo(() => kingSquareInCheck(fen), [fen]);

  const pieceColorAt = (square: string): "w" | "b" | null => {
    const piece = safeChess(fen)?.get(square as never);
    return piece ? piece.color : null;
  };

  const attempt = (from: string, to: string): boolean => {
    if (!canMoveNow || !onMove) return false;
    if (!targets.get(from)?.includes(to)) return false;
    if (isPromotion(fen, from, to)) {
      setPendingPromotion({ from, to });
      return false;
    }
    const accepted = onMove({ from, to });
    setSelected(null);
    return accepted !== false;
  };

  const squareStyles: Record<string, CSSProperties> = {};
  const add = (square: string, style: CSSProperties) => {
    squareStyles[square] = { ...squareStyles[square], ...style };
  };
  if (lastMove) {
    add(lastMove.from, { backgroundColor: HIGHLIGHT_LAST });
    add(lastMove.to, { backgroundColor: HIGHLIGHT_LAST });
  }
  if (checkSquare) {
    add(checkSquare, { background: "radial-gradient(circle, rgba(239,90,82,0.95) 0%, rgba(239,90,82,0.55) 35%, rgba(239,90,82,0) 72%)" });
  }
  if (selected) {
    add(selected, { backgroundColor: HIGHLIGHT_SELECTED });
    for (const target of targets.get(selected) ?? []) {
      const occupied = pieceColorAt(target) !== null;
      add(target, {
        backgroundImage: occupied
          ? "radial-gradient(circle, transparent 58%, rgba(20,22,25,0.38) 60%)"
          : "radial-gradient(circle, rgba(20,22,25,0.32) 21%, transparent 23%)",
        cursor: "pointer",
      });
    }
  }
  for (const [square, style] of Object.entries(squareMarkers ?? {})) add(square, style);

  const promotionColor = turn;
  const promotionFile = pendingPromotion ? pendingPromotion.to.charCodeAt(0) - 97 : 0;
  const column = orientation === "white" ? promotionFile : 7 - promotionFile;
  const promotionAtTop = pendingPromotion ? (pendingPromotion.to[1] === "8") === (orientation === "white") : true;

  const description = useMemo(() => describePosition(fen), [fen]);
  const descriptionId = `${id}-description`;

  return (
    <div className="relative aspect-square w-full select-none" aria-label={ariaLabel ?? "Chessboard"} aria-describedby={descriptionId} role="group">
      <p id={descriptionId} className="sr-only">
        {description}
      </p>
      <Chessboard
        options={{
          id,
          position: fen,
          boardOrientation: orientation,
          showNotation: showCoordinates,
          showAnimations: animations,
          animationDurationInMs: 180,
          allowDragging: canMoveNow && Boolean(onMove),
          allowDrawingArrows: true,
          clearArrowsOnPositionChange: true,
          arrows: arrows.map((a) => ({ startSquare: a.from, endSquare: a.to, color: a.color ?? "rgba(127,178,255,0.8)" })),
          darkSquareStyle: { backgroundColor: theme.dark },
          lightSquareStyle: { backgroundColor: theme.light },
          boardStyle: { borderRadius: "10px", overflow: "hidden", boxShadow: "0 18px 50px -20px rgba(0,0,0,0.85)" },
          darkSquareNotationStyle: { color: theme.light, fontWeight: 600, fontSize: "11px" },
          lightSquareNotationStyle: { color: theme.dark, fontWeight: 600, fontSize: "11px" },
          dropSquareStyle: { boxShadow: "inset 0 0 0 3px rgba(214,167,86,0.8)" },
          squareStyles,
          canDragPiece: ({ piece }) => canMoveNow && piece.pieceType[0] === turn,
          onPieceDrop: ({ sourceSquare, targetSquare }) => (targetSquare ? attempt(sourceSquare, targetSquare) : false),
          onSquareClick: ({ square }) => {
            if (pendingPromotion) return;
            if (selected && selected !== square && targets.get(selected)?.includes(square)) {
              attempt(selected, square);
              return;
            }
            const color = pieceColorAt(square);
            if (canMoveNow && color === turn && targets.has(square)) setSelected(square === selected ? null : square);
            else setSelected(null);
          },
        }}
      />

      {pendingPromotion && (
        <div className="absolute inset-0 z-20 bg-black/45" onClick={() => setPendingPromotion(null)}>
          <div
            role="dialog"
            aria-label="Choose promotion piece"
            className="absolute flex w-[12.5%] flex-col overflow-hidden rounded-md border border-brass-500/60 bg-ink-850 shadow-2xl"
            style={{ left: `${column * 12.5}%`, ...(promotionAtTop ? { top: 0 } : { bottom: 0 }), flexDirection: promotionAtTop ? "column" : "column-reverse" }}
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.key === "Escape" && setPendingPromotion(null)}
          >
            {(["q", "r", "b", "n"] as const).map((piece, index) => {
              const key = `${promotionColor}${piece.toUpperCase()}`;
              const render = defaultPieces[key];
              return (
                <button
                  key={piece}
                  type="button"
                  autoFocus={index === 0}
                  aria-label={`Promote to ${{ q: "queen", r: "rook", b: "bishop", n: "knight" }[piece]}`}
                  className="aspect-square w-full p-[8%] transition-colors hover:bg-brass-500/25 focus-visible:bg-brass-500/25"
                  onClick={() => {
                    const move = { from: pendingPromotion.from, to: pendingPromotion.to, promotion: piece };
                    setPendingPromotion(null);
                    setSelected(null);
                    onMove?.(move);
                  }}
                >
                  {render ? render() : piece.toUpperCase()}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
