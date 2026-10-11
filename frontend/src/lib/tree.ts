// An immutable move tree with variations, used by the analysis board.
// children[0] of a node is its main continuation; later children are variations.

import { Chess } from "chess.js";
import type { ServerTreeNode } from "@/types/api";

export const START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

export interface TreeNode {
  id: string;
  parent: string | null;
  ply: number;
  fen: string;
  san: string | null;
  uci: string | null;
  children: string[];
  comment?: string | null;
  clock?: number | null;
}

export interface GameTree {
  rootId: string;
  nodes: Record<string, TreeNode>;
  nextId: number;
  headers: Record<string, string>;
}

export function createTree(fen: string = START_FEN, headers: Record<string, string> = {}): GameTree {
  const root: TreeNode = { id: "n0", parent: null, ply: plyFromFen(fen), fen, san: null, uci: null, children: [] };
  return { rootId: root.id, nodes: { [root.id]: root }, nextId: 1, headers };
}

/** Half-move count implied by a FEN (so numbering works for set-up positions). */
export function plyFromFen(fen: string): number {
  const parts = fen.split(" ");
  const fullmove = Number(parts[5] ?? "1") || 1;
  return (fullmove - 1) * 2 + (parts[1] === "b" ? 1 : 0);
}

export function getNode(tree: GameTree, id: string): TreeNode {
  const node = tree.nodes[id];
  if (!node) throw new Error(`unknown node ${id}`);
  return node;
}

/** Add a move after `parentId` (reusing an existing identical child). */
export function addMove(
  tree: GameTree,
  parentId: string,
  move: { san: string; uci: string; fen: string },
): { tree: GameTree; id: string } {
  const parent = getNode(tree, parentId);
  const existing = parent.children.find((c) => getNode(tree, c).uci === move.uci);
  if (existing) return { tree, id: existing };
  const id = `n${tree.nextId}`;
  const node: TreeNode = { id, parent: parentId, ply: parent.ply + 1, fen: move.fen, san: move.san, uci: move.uci, children: [] };
  return {
    id,
    tree: {
      ...tree,
      nextId: tree.nextId + 1,
      nodes: { ...tree.nodes, [id]: node, [parentId]: { ...parent, children: [...parent.children, id] } },
    },
  };
}

/** Node ids from the root to `id` (inclusive). */
export function pathTo(tree: GameTree, id: string): string[] {
  const path: string[] = [];
  let current: string | null = id;
  while (current) {
    path.push(current);
    current = getNode(tree, current).parent;
  }
  return path.reverse();
}

/** UCI moves from the root to `id` (what the backend needs to rebuild history). */
export function movesTo(tree: GameTree, id: string): string[] {
  return pathTo(tree, id)
    .map((n) => getNode(tree, n).uci)
    .filter((u): u is string => Boolean(u));
}

/** Main line starting at `id` (following first children). */
export function mainlineFrom(tree: GameTree, id: string): string[] {
  const line = [id];
  let node = getNode(tree, id);
  while (node.children[0]) {
    node = getNode(tree, node.children[0]);
    line.push(node.id);
  }
  return line;
}

export function isOnMainline(tree: GameTree, id: string): boolean {
  let node = getNode(tree, id);
  while (node.parent) {
    const parent = getNode(tree, node.parent);
    if (parent.children[0] !== node.id) return false;
    node = parent;
  }
  return true;
}

/** Remove a node and its subtree. */
export function deleteSubtree(tree: GameTree, id: string): GameTree {
  const node = getNode(tree, id);
  if (!node.parent) return tree;
  const nodes = { ...tree.nodes };
  const stack = [id];
  while (stack.length) {
    const current = stack.pop()!;
    stack.push(...(nodes[current]?.children ?? []));
    delete nodes[current];
  }
  const parent = getNode(tree, node.parent);
  nodes[parent.id] = { ...parent, children: parent.children.filter((c) => c !== id) };
  return { ...tree, nodes };
}

/** Make the variation containing `id` the main line at its branch point. */
export function promoteVariation(tree: GameTree, id: string): GameTree {
  let child = getNode(tree, id);
  while (child.parent) {
    const parent = getNode(tree, child.parent);
    if (parent.children[0] !== child.id) {
      const children = [child.id, ...parent.children.filter((c) => c !== child.id)];
      return { ...tree, nodes: { ...tree.nodes, [parent.id]: { ...parent, children } } };
    }
    child = parent;
  }
  return tree;
}

/** Build a tree from the backend's parsed PGN nodes. */
export function fromServerNodes(nodes: ServerTreeNode[], headers: Record<string, string> = {}): GameTree {
  const tree: GameTree = { rootId: "n0", nodes: {}, nextId: nodes.length, headers };
  for (const n of nodes) {
    tree.nodes[`n${n.id}`] = {
      id: `n${n.id}`,
      parent: n.parent === null ? null : `n${n.parent}`,
      ply: n.ply,
      fen: n.fen,
      san: n.san,
      uci: n.uci,
      children: n.children.map((c) => `n${c}`),
      comment: n.comment,
      clock: n.clock,
    };
  }
  const root = tree.nodes.n0;
  if (root) {
    const offset = plyFromFen(root.fen);
    for (const node of Object.values(tree.nodes)) node.ply += offset;
  }
  return tree;
}

/** Build a linear tree from a list of UCI moves (e.g. a stored game). */
export function fromMoves(startFen: string, moves: string[], headers: Record<string, string> = {}): GameTree {
  let tree = createTree(startFen, headers);
  const chess = new Chess(startFen);
  let current = tree.rootId;
  for (const uci of moves) {
    const played = chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
    const result = addMove(tree, current, { san: played.san, uci, fen: chess.fen() });
    tree = result.tree;
    current = result.id;
  }
  return tree;
}

function moveNumberPrefix(ply: number, forceBlack: boolean): string {
  // `ply` is the ply *after* the move; the move itself was made at ply - 1.
  const moverPly = ply - 1;
  const number = Math.floor(moverPly / 2) + 1;
  if (moverPly % 2 === 0) return `${number}. `;
  return forceBlack ? `${number}... ` : "";
}

function escapeComment(text: string): string {
  return text.replace(/[{}]/g, "");
}

/** Export the tree (with variations and comments) as PGN text. */
export function toPgn(tree: GameTree, extraHeaders: Record<string, string> = {}): string {
  const root = getNode(tree, tree.rootId);
  const headers: Record<string, string> = {
    Event: "ChessLab analysis",
    Site: "ChessLab",
    Date: new Date().toISOString().slice(0, 10).replace(/-/g, "."),
    Round: "-",
    White: "?",
    Black: "?",
    Result: "*",
    ...tree.headers,
    ...extraHeaders,
  };
  if (root.fen !== START_FEN) {
    headers.SetUp = "1";
    headers.FEN = root.fen;
  }
  const tokens: string[] = [];

  const writeLine = (startId: string, forceNumber: boolean) => {
    let id: string | undefined = startId;
    let force = forceNumber;
    while (id) {
      const node = getNode(tree, id);
      tokens.push(`${moveNumberPrefix(node.ply, force)}${node.san}`);
      if (node.comment) tokens.push(`{ ${escapeComment(node.comment)} }`);
      force = Boolean(node.comment);
      const parent = getNode(tree, node.parent!);
      // Variations of this move are alternatives to it, written right after it.
      if (parent.children[0] === id && parent.children.length > 1) {
        for (const alt of parent.children.slice(1)) {
          tokens.push("(");
          writeLine(alt, true);
          tokens.push(")");
        }
        force = true;
      }
      id = node.children[0];
    }
  };

  if (root.children[0]) writeLine(root.children[0], true);
  tokens.push(headers.Result ?? "*");
  const headerText = Object.entries(headers)
    .map(([k, v]) => `[${k} "${String(v).replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"]`)
    .join("\n");
  const body = tokens.join(" ").replace(/\( /g, "(").replace(/ \)/g, ")");
  return `${headerText}\n\n${wrap(body, 80)}\n`;
}

function wrap(text: string, width: number): string {
  const words = text.split(" ");
  const lines: string[] = [];
  let line = "";
  for (const word of words) {
    if (line && line.length + word.length + 1 > width) {
      lines.push(line);
      line = word;
    } else {
      line = line ? `${line} ${word}` : word;
    }
  }
  if (line) lines.push(line);
  return lines.join("\n");
}
