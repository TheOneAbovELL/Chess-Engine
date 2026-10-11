// The analysis board's state lives in a store so it survives navigation
// (e.g. Settings and back) and other pages can hand a game to it.

import { create } from "zustand";
import { addMove, createTree, getNode, type GameTree, START_FEN } from "@/lib/tree";

interface AnalysisState {
  tree: GameTree;
  currentId: string;
  orientation: "white" | "black";
  /** Remembers which child we came back from, so "forward" retraces it (redo). */
  lastVisited: Record<string, string>;
  load: (tree: GameTree, currentId?: string, orientation?: "white" | "black") => void;
  reset: (fen?: string) => void;
  goTo: (id: string) => void;
  play: (move: { san: string; uci: string; fen: string }) => void;
  setTree: (tree: GameTree, currentId?: string) => void;
  flip: () => void;
  back: () => void;
  forward: () => void;
  first: () => void;
  last: () => void;
}

export const useAnalysisStore = create<AnalysisState>((set, get) => ({
  tree: createTree(START_FEN),
  currentId: "n0",
  orientation: "white",
  lastVisited: {},
  load: (tree, currentId, orientation) => set({ tree, currentId: currentId ?? tree.rootId, lastVisited: {}, ...(orientation ? { orientation } : {}) }),
  reset: (fen = START_FEN) => set({ tree: createTree(fen), currentId: "n0", lastVisited: {} }),
  goTo: (id) => set({ currentId: id }),
  play: (move) => {
    const { tree, currentId } = get();
    const result = addMove(tree, currentId, move);
    set({ tree: result.tree, currentId: result.id });
  },
  setTree: (tree, currentId) => set((s) => ({ tree, currentId: currentId ?? (tree.nodes[s.currentId] ? s.currentId : tree.rootId) })),
  flip: () => set((s) => ({ orientation: s.orientation === "white" ? "black" : "white" })),
  back: () => {
    const { tree, currentId, lastVisited } = get();
    const node = getNode(tree, currentId);
    if (node.parent) set({ currentId: node.parent, lastVisited: { ...lastVisited, [node.parent]: currentId } });
  },
  forward: () => {
    const { tree, currentId, lastVisited } = get();
    const node = getNode(tree, currentId);
    const remembered = lastVisited[currentId];
    const next = remembered && node.children.includes(remembered) ? remembered : node.children[0];
    if (next) set({ currentId: next });
  },
  first: () => set((s) => ({ currentId: s.tree.rootId })),
  last: () => {
    const { tree } = get();
    let node = getNode(tree, get().currentId);
    while (node.children[0]) node = getNode(tree, node.children[0]);
    set({ currentId: node.id });
  },
}));
