import { Chess } from "chess.js";
import { describe, expect, it } from "vitest";
import {
  addMove,
  createTree,
  deleteSubtree,
  fromMoves,
  fromServerNodes,
  getNode,
  isOnMainline,
  mainlineFrom,
  movesTo,
  plyFromFen,
  promoteVariation,
  START_FEN,
  toPgn,
} from "./tree";
import { tryMove } from "./chess";

function play(tree: ReturnType<typeof createTree>, from: string, ucis: string[]) {
  let t = tree;
  let id = from;
  for (const uci of ucis) {
    const move = tryMove(getNode(t, id).fen, uci.slice(0, 2), uci.slice(2, 4), uci[4]);
    if (!move) throw new Error(`illegal ${uci}`);
    const r = addMove(t, id, move);
    t = r.tree;
    id = r.id;
  }
  return { tree: t, id };
}

describe("game tree", () => {
  it("adds moves, reuses identical children and tracks the path", () => {
    const { tree, id } = play(createTree(), "n0", ["e2e4", "e7e5", "g1f3"]);
    expect(movesTo(tree, id)).toEqual(["e2e4", "e7e5", "g1f3"]);
    const again = addMove(tree, "n0", { san: "e4", uci: "e2e4", fen: getNode(tree, "n1").fen });
    expect(again.tree).toBe(tree); // no duplicate child
    expect(getNode(tree, id).ply).toBe(3);
  });

  it("keeps variations and can promote or delete them", () => {
    const main = play(createTree(), "n0", ["e2e4", "e7e5", "g1f3"]);
    const variation = play(main.tree, "n1", ["c7c5", "g1f3"]); // 1...c5 instead of 1...e5
    const tree = variation.tree;
    expect(getNode(tree, "n1").children).toHaveLength(2);
    expect(isOnMainline(tree, variation.id)).toBe(false);
    expect(mainlineFrom(tree, "n0")).toHaveLength(4);

    const promoted = promoteVariation(tree, variation.id);
    expect(isOnMainline(promoted, variation.id)).toBe(true);
    expect(movesTo(promoted, mainlineFrom(promoted, "n0").at(-1)!)).toEqual(["e2e4", "c7c5", "g1f3"]);

    const pruned = deleteSubtree(tree, getNode(tree, "n1").children[1]!);
    expect(getNode(pruned, "n1").children).toHaveLength(1);
    expect(Object.keys(pruned.nodes)).toHaveLength(4);
  });

  it("exports PGN with variations that chess.js can read back", () => {
    const main = play(createTree(), "n0", ["e2e4", "e7e5", "g1f3", "b8c6"]);
    const tree = play(main.tree, "n1", ["c7c5", "g1f3", "d7d6"]).tree;
    const pgn = toPgn(tree, { White: "Alice", Black: "Bob" });
    expect(pgn).toContain('[White "Alice"]');
    expect(pgn).toContain("1. e4 e5 (1... c5 2. Nf3 d6) 2. Nf3 Nc6 *");
    const chess = new Chess();
    chess.loadPgn(pgn); // mainline must be valid
    expect(chess.history()).toEqual(["e4", "e5", "Nf3", "Nc6"]);
  });

  it("numbers moves correctly from a set-up position with Black to move", () => {
    const fen = "4k3/8/8/8/8/8/4P3/4K3 b - - 0 40";
    expect(plyFromFen(fen)).toBe(79);
    const { tree } = play(createTree(fen), "n0", ["e8d8", "e2e4"]);
    const pgn = toPgn(tree);
    expect(pgn).toContain('[FEN "4k3/8/8/8/8/8/4P3/4K3 b - - 0 40"]');
    expect(pgn).toContain("40... Kd8 41. e4");
  });

  it("builds trees from server nodes and plain move lists", () => {
    const tree = fromServerNodes([
      { id: 0, parent: null, ply: 0, fen: START_FEN, san: null, uci: null, comment: null, nags: [], clock: null, children: [1] },
      { id: 1, parent: 0, ply: 1, fen: "x", san: "e4", uci: "e2e4", comment: "good", nags: [], clock: 300, children: [] },
    ]);
    expect(getNode(tree, "n1").comment).toBe("good");
    expect(getNode(tree, "n1").ply).toBe(1);
    const linear = fromMoves(START_FEN, ["d2d4", "d7d5"]);
    expect(mainlineFrom(linear, "n0")).toEqual(["n0", "n1", "n2"]);
    expect(getNode(linear, "n2").san).toBe("d5");
  });
});
