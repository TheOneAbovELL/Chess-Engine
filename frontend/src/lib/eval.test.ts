import { describe, expect, it } from "vitest";
import { describeEval, formatEval, graphValue, whiteExpectedScore } from "./eval";
import { gameStatus, isPromotion, legalTargets, parseTypedMove, safeChess, tryMove, uciLineToSan } from "./chess";
import { formatClock, formatPercent } from "./format";

describe("evaluation helpers", () => {
  it("formats centipawns and mates from White's point of view", () => {
    expect(formatEval({ cp: 32, mate: null })).toBe("+0.32");
    expect(formatEval({ cp: -150, mate: null })).toBe("-1.50");
    expect(formatEval({ cp: 0, mate: null })).toBe("0.00");
    expect(formatEval({ cp: null, mate: 3 })).toBe("M3");
    expect(formatEval({ cp: null, mate: -2 })).toBe("-M2");
    expect(formatEval({ cp: null, mate: 0 }, "w")).toBe("0-1"); // White is mated
    expect(formatEval(null)).toBe("–");
  });

  it("uses the same expected-score curve as the backend", () => {
    expect(whiteExpectedScore({ cp: 0, mate: null })).toBeCloseTo(0.5);
    expect(whiteExpectedScore({ cp: 100, mate: null })).toBeCloseTo(0.591, 3);
    expect(whiteExpectedScore({ cp: null, mate: 4 })).toBe(1);
    expect(whiteExpectedScore({ cp: null, mate: 0 }, "b")).toBe(1);
    expect(graphValue({ cp: 5000, mate: null })).toBe(1000);
  });

  it("describes evaluations in hedged plain language", () => {
    expect(describeEval({ cp: 10, mate: null })).toBe("Roughly equal");
    expect(describeEval({ cp: -250, mate: null })).toBe("Black is winning");
    expect(describeEval({ cp: null, mate: 2 })).toBe("White has a forced mate in 2");
  });
});

describe("chess helpers", () => {
  it("lists legal targets and rejects illegal moves", () => {
    const targets = legalTargets("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
    expect(targets.get("e2")).toEqual(["e3", "e4"]);
    expect(targets.get("g1")?.sort()).toEqual(["f3", "h3"]);
    expect(tryMove("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "e2", "e5")).toBeNull();
  });

  it("detects promotions and parses typed moves", () => {
    const fen = "8/P6k/8/8/8/8/8/K7 w - - 0 1";
    expect(isPromotion(fen, "a7", "a8")).toBe(true);
    expect(tryMove(fen, "a7", "a8", "n")?.san).toBe("a8=N");
    expect(parseTypedMove("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "Nf3")?.uci).toBe("g1f3");
    expect(parseTypedMove("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "e2e4")?.san).toBe("e4");
    expect(parseTypedMove("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "Qh5")).toBeNull();
  });

  it("reports game-ending states", () => {
    const mate = safeChess("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")!;
    expect(gameStatus(mate)).toMatchObject({ over: true, result: "0-1", reason: "checkmate" });
    const stalemate = safeChess("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")!;
    expect(gameStatus(stalemate)).toMatchObject({ over: true, result: "1/2-1/2", reason: "stalemate" });
    const bare = safeChess("8/8/4k3/8/8/4K3/8/8 w - - 0 1")!;
    expect(gameStatus(bare).reason).toBe("insufficient material");
  });

  it("converts engine lines to SAN and stops at illegal moves", () => {
    const start = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
    expect(uciLineToSan(start, ["e2e4", "e7e5", "e7e5"])).toEqual(["e4", "e5"]);
  });

  it("formats clocks and percentages", () => {
    expect(formatClock(65)).toBe("1:05");
    expect(formatClock(3725)).toBe("1:02:05");
    expect(formatPercent(0.537, 1)).toBe("53.7%");
  });
});
