import { ChevronFirst, ChevronLast, ChevronLeft, ChevronRight, FlipVertical2 } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { IconButton } from "@/components/ui";
import { parseTypedMove } from "@/lib/chess";

interface NavProps {
  onFirst: () => void;
  onPrev: () => void;
  onNext: () => void;
  onLast: () => void;
  onFlip?: () => void;
  canBack: boolean;
  canForward: boolean;
  children?: React.ReactNode;
}

export function BoardNav({ onFirst, onPrev, onNext, onLast, onFlip, canBack, canForward, children }: NavProps) {
  return (
    <div className="flex items-center justify-between gap-2">
      <div className="flex items-center gap-0.5">
        <IconButton label="First move (Home)" onClick={onFirst} disabled={!canBack}>
          <ChevronFirst className="size-5" />
        </IconButton>
        <IconButton label="Previous move (←)" onClick={onPrev} disabled={!canBack}>
          <ChevronLeft className="size-5" />
        </IconButton>
        <IconButton label="Next move (→)" onClick={onNext} disabled={!canForward}>
          <ChevronRight className="size-5" />
        </IconButton>
        <IconButton label="Last move (End)" onClick={onLast} disabled={!canForward}>
          <ChevronLast className="size-5" />
        </IconButton>
        {onFlip && (
          <IconButton label="Flip board (F)" onClick={onFlip}>
            <FlipVertical2 className="size-4" />
          </IconButton>
        )}
      </div>
      {children && <div className="flex items-center gap-1">{children}</div>}
    </div>
  );
}

/** Keyboard navigation shared by board pages (ignored while typing in inputs). */
export function useBoardKeys(handlers: Partial<Record<"prev" | "next" | "first" | "last" | "flip", () => void>>) {
  // Keep the newest handlers in a ref so callers need not memoise them.
  const ref = useRef(handlers);
  useEffect(() => {
    ref.current = handlers;
  });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable)) return;
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      const map: Record<string, keyof typeof handlers> = { ArrowLeft: "prev", ArrowRight: "next", Home: "first", End: "last", f: "flip", F: "flip" };
      const action = map[e.key];
      const handler = action ? ref.current[action] : undefined;
      if (handler) {
        e.preventDefault();
        handler();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

/** Type a move in SAN or UCI: a keyboard-accessible alternative to dragging. */
export function MoveInput({ fen, onMove, disabled }: { fen: string; onMove: (uci: string) => void; disabled?: boolean }) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const parsed = parseTypedMove(fen, text);
    if (!parsed) {
      setError(`"${text}" is not a legal move here.`);
      return;
    }
    setError(null);
    setText("");
    onMove(parsed.uci);
  };
  return (
    <form onSubmit={submit} className="space-y-1">
      <label className="sr-only" htmlFor="move-input">
        Type a move
      </label>
      <input
        id="move-input"
        className="field num h-8 text-xs"
        placeholder="Type a move (Nf3 or g1f3) and press Enter"
        value={text}
        disabled={disabled}
        onChange={(e) => {
          setText(e.target.value);
          setError(null);
        }}
        autoComplete="off"
        spellCheck={false}
      />
      {error && <p className="text-xs text-[#ff8f88]">{error}</p>}
    </form>
  );
}
