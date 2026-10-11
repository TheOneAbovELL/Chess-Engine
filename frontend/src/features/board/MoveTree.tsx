// Move list with nested variations. Clicking a move jumps to it.

import { useEffect, useRef, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { MOVE_CLASS_META } from "@/lib/eval";
import { getNode, type GameTree } from "@/lib/tree";
import type { MoveClass } from "@/types/api";

interface MoveTreeProps {
  tree: GameTree;
  currentId: string;
  onSelect: (id: string) => void;
  annotations?: Record<string, MoveClass | null | undefined>;
  emptyHint?: ReactNode;
}

export function MoveTree({ tree, currentId, onSelect, annotations, emptyHint }: MoveTreeProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const root = getNode(tree, tree.rootId);

  useEffect(() => {
    const el = containerRef.current?.querySelector<HTMLElement>(`[data-node="${currentId}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [currentId]);

  if (!root.children.length) {
    return <div className="px-4 py-6 text-center text-sm text-ink-400">{emptyHint ?? "Make a move on the board to start."}</div>;
  }

  const moveButton = (id: string, showNumber: boolean) => {
    const node = getNode(tree, id);
    const moverPly = node.ply - 1;
    const number = Math.floor(moverPly / 2) + 1;
    const isWhite = moverPly % 2 === 0;
    const cls = annotations?.[id];
    const meta = cls ? MOVE_CLASS_META[cls] : null;
    return (
      <button
        key={id}
        type="button"
        data-node={id}
        onClick={() => onSelect(id)}
        aria-current={id === currentId ? "true" : undefined}
        className={cn(
          "num inline-flex items-baseline gap-0.5 rounded px-1 py-0.5 text-[13px] transition-colors",
          id === currentId ? "bg-brass-500 text-ink-950" : "text-ink-100 hover:bg-ink-700",
        )}
      >
        {(isWhite || showNumber) && <span className={cn("mr-0.5", id === currentId ? "text-ink-900/70" : "text-ink-400")}>{isWhite ? `${number}.` : `${number}...`}</span>}
        {node.san}
        {meta && cls !== "best" && cls !== "excellent" && cls !== "good" && (
          <span className="ml-0.5 font-bold" style={{ color: id === currentId ? undefined : meta.color }}>
            {meta.symbol}
          </span>
        )}
      </button>
    );
  };

  // Render a line: main moves inline, variations as indented blocks.
  const renderLine = (startId: string, depth: number): ReactNode[] => {
    const out: ReactNode[] = [];
    let id: string | undefined = startId;
    let forceNumber = true;
    while (id) {
      const node = getNode(tree, id);
      out.push(moveButton(id, forceNumber));
      forceNumber = false;
      const parent = getNode(tree, node.parent!);
      if (parent.children[0] === id && parent.children.length > 1) {
        for (const alt of parent.children.slice(1)) {
          out.push(
            <div key={`var-${alt}`} className={cn("my-1 w-full border-l-2 border-ink-600 py-0.5 pl-2", depth > 2 && "border-ink-700")}>
              <div className="flex flex-wrap items-baseline gap-x-0.5 text-ink-300">{renderLine(alt, depth + 1)}</div>
            </div>,
          );
        }
        forceNumber = true;
      }
      id = node.children[0];
    }
    return out;
  };

  return (
    <div ref={containerRef} className="flex flex-wrap content-start items-baseline gap-x-0.5 gap-y-0.5 p-3" aria-label="Moves">
      {renderLine(root.children[0]!, 0)}
    </div>
  );
}
