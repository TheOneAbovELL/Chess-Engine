import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDialog, WdlBar } from "@/components/ui";
import { addMove, createTree } from "@/lib/tree";
import { MoveInput, useBoardKeys } from "./board/BoardControls";
import { EvalBar } from "./board/EvalBar";
import { MoveTree } from "./board/MoveTree";
import { EngineLines } from "./analysis/EngineLines";
import type { AnalysisSnapshot } from "@/types/api";

const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

describe("EvalBar", () => {
  it("exposes the evaluation accessibly", () => {
    render(<EvalBar evaluation={{ cp: 150, mate: null }} />);
    const meter = screen.getByRole("meter");
    expect(meter).toHaveAttribute("aria-label", expect.stringContaining("White is clearly better"));
    expect(Number(meter.getAttribute("aria-valuenow"))).toBeGreaterThan(60);
  });
});

describe("MoveInput", () => {
  it("accepts SAN and reports illegal input", async () => {
    const onMove = vi.fn();
    render(<MoveInput fen={START} onMove={onMove} />);
    const input = screen.getByLabelText("Type a move");
    await userEvent.type(input, "Nf3{enter}");
    expect(onMove).toHaveBeenCalledWith("g1f3");
    await userEvent.type(input, "Ke2{enter}");
    expect(screen.getByText(/not a legal move/)).toBeInTheDocument();
    expect(onMove).toHaveBeenCalledTimes(1);
  });
});

describe("MoveTree", () => {
  it("renders moves with numbers and selects on click", async () => {
    let tree = createTree();
    tree = addMove(tree, "n0", { san: "e4", uci: "e2e4", fen: "x1" }).tree;
    tree = addMove(tree, "n1", { san: "e5", uci: "e7e5", fen: "x2" }).tree;
    tree = addMove(tree, "n1", { san: "c5", uci: "c7c5", fen: "x3" }).tree; // variation
    const onSelect = vi.fn();
    render(<MoveTree tree={tree} currentId="n2" onSelect={onSelect} annotations={{ n2: "blunder" }} />);
    expect(screen.getByRole("button", { name: /1\.e4/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /1\.\.\.c5/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /e5\?\?/ })).toHaveAttribute("aria-current", "true");
    await userEvent.click(screen.getByRole("button", { name: /1\.\.\.c5/ }));
    expect(onSelect).toHaveBeenCalledWith("n3");
  });
});

describe("EngineLines", () => {
  const snapshot: AnalysisSnapshot = {
    engine_id: "stockfish",
    engine_name: "Stockfish 19",
    fen: START,
    depth: 18,
    seldepth: 25,
    nodes: 1_200_000,
    nps: 900_000,
    time_ms: 1300,
    hashfull: 40,
    lines: [
      { multipv: 1, depth: 18, seldepth: 25, score: { cp: 31, mate: null }, pv: ["e2e4", "e7e5"], pv_san: ["e4", "e5"] },
      { multipv: 2, depth: 18, seldepth: 22, score: { cp: -12, mate: null }, pv: ["a2a3", "e7e5"], pv_san: ["a3", "e5"] },
    ],
    best_move: "e2e4",
    best_move_san: "e4",
    ponder: "e7e5",
    final: false,
    stop_reason: null,
    terminal: null,
  };

  it("shows each candidate line with its evaluation and plays a line on click", async () => {
    const onPlay = vi.fn();
    render(<EngineLines snapshot={snapshot} fen={START} running onPlayLine={onPlay} />);
    expect(screen.getByText("+0.31")).toBeInTheDocument();
    expect(screen.getByText("-0.12")).toBeInTheDocument();
    expect(screen.getByText("Stockfish 19")).toBeInTheDocument();
    await userEvent.click(screen.getAllByTitle("Play this line up to here")[1]!);
    expect(onPlay).toHaveBeenCalledWith(["e2e4", "e7e5"]);
  });

  it("shows loading skeletons while waiting and a game-over message at the end", () => {
    const { container, rerender } = render(<EngineLines snapshot={null} fen={START} running />);
    expect(container.querySelectorAll(".skeleton")).toHaveLength(3);
    rerender(<EngineLines snapshot={{ ...snapshot, lines: [], terminal: "checkmate" }} fen={START} running={false} />);
    expect(screen.getByText(/Checkmate/)).toBeInTheDocument();
  });
});

function KeysProbe({ onPrev }: { onPrev: () => void }) {
  useBoardKeys({ prev: onPrev });
  return <input aria-label="text field" />;
}

describe("useBoardKeys", () => {
  it("handles arrow keys but ignores typing in inputs", () => {
    const onPrev = vi.fn();
    render(<KeysProbe onPrev={onPrev} />);
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(onPrev).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(screen.getByLabelText("text field"), { key: "ArrowLeft" });
    expect(onPrev).toHaveBeenCalledTimes(1);
  });
});

describe("ConfirmDialog and WdlBar", () => {
  it("requires an explicit confirmation", async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(<ConfirmDialog open title="Delete?" message="Really?" confirmLabel="Delete" danger onConfirm={onConfirm} onCancel={onCancel} />);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onConfirm).toHaveBeenCalled();
  });

  it("describes results for screen readers", () => {
    render(<WdlBar wins={3} draws={1} losses={2} />);
    expect(screen.getByRole("img", { name: "3 wins, 1 draws, 2 losses" })).toBeInTheDocument();
  });
});
