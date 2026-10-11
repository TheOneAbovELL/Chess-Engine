"""Transposition table.

Positions are keyed by python-chess's Zobrist hash (``chess.polyglot.zobrist_hash``),
a 64-bit hash computed from the piece placement, side to move, castling rights and
en-passant square. It is recomputed for each node rather than updated
incrementally; incremental hashing belongs to the planned faster implementation
(see docs/engine-design.md).

Python dicts are used for storage. ``capacity`` is derived from the UCI ``Hash``
option using a conservative estimate of the per-entry memory cost of a Python
tuple stored in a dict.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

EXACT, LOWER, UPPER = 0, 1, 2
BYTES_PER_ENTRY = 200  # rough CPython cost of key + tuple + dict slot


@dataclass(slots=True)
class TTEntry:
    depth: int
    score: int
    flag: int
    move: chess.Move | None


class TranspositionTable:
    def __init__(self, size_mb: int = 32) -> None:
        self.resize(size_mb)

    def resize(self, size_mb: int) -> None:
        self.capacity = max(1024, size_mb * 1024 * 1024 // BYTES_PER_ENTRY)
        self.table: dict[int, TTEntry] = {}

    def clear(self) -> None:
        self.table.clear()

    def get(self, key: int) -> TTEntry | None:
        return self.table.get(key)

    def store(self, key: int, depth: int, score: int, flag: int, move: chess.Move | None) -> None:
        existing = self.table.get(key)
        # Depth-preferred replacement; always keep a best move if we had one.
        if existing is not None:
            if existing.depth > depth and flag != EXACT:
                return
            if move is None:
                move = existing.move
        elif len(self.table) >= self.capacity:
            # Evict the oldest quarter (dicts preserve insertion order).
            for old_key in list(self.table.keys())[: self.capacity // 4]:
                del self.table[old_key]
        self.table[key] = TTEntry(depth, score, flag, move)

    def hashfull(self) -> int:
        """Occupancy in permille, as reported by UCI ``info hashfull``."""
        return min(1000, len(self.table) * 1000 // self.capacity)
