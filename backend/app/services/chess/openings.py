"""Opening names from the Lichess chess-openings dataset (CC0).

Every line of the dataset names the position reached after its moves. Positions
are indexed by EPD (piece placement, side to move, castling, en passant), so a
transposed move order still finds its name. A game is named after the deepest
named position it passes through, which is how chess sites name openings too.
"""

from __future__ import annotations

import csv
import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path

import chess

from .normalize import GameRecord

log = logging.getLogger("chesslab.openings")
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "openings"
BOOK_VERSION = 1  # bump when the dataset or matching rules change (triggers a backfill)
MAX_SCAN_PLIES = 40  # the longest named line is shorter than this
_MOVE_NUMBER = re.compile(r"^\d+\.+$")


@dataclass(frozen=True)
class Opening:
    eco: str
    name: str
    ply: int  # length of the line that names this position

    @property
    def family(self) -> str:
        return self.name.split(":")[0].strip()


class OpeningBook:
    def __init__(self, directory: Path = DATA_DIR) -> None:
        self.directory = directory
        self._positions: dict[str, Opening] | None = None
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Opening]:
        positions: dict[str, Opening] = {}
        files = sorted(self.directory.glob("*.tsv"))
        for path in files:
            with path.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle, delimiter="\t"):
                    board = chess.Board()
                    ply = 0
                    try:
                        for token in row["pgn"].split():
                            if _MOVE_NUMBER.match(token):
                                continue
                            board.push_san(token)
                            ply += 1
                    except (ValueError, KeyError):
                        continue  # a malformed row never breaks the book
                    key = board.epd()
                    existing = positions.get(key)
                    # Several lines can reach one position; keep the most general (shortest) name.
                    if existing is None or ply < existing.ply:
                        positions[key] = Opening(row["eco"], row["name"], ply)
        log.info("opening book loaded", extra={"positions": len(positions), "files": len(files)})
        return positions

    @property
    def positions(self) -> dict[str, Opening]:
        if self._positions is None:
            with self._lock:
                if self._positions is None:
                    self._positions = self._load()
        return self._positions

    def __len__(self) -> int:
        return len(self.positions)

    def lookup(self, board: chess.Board) -> Opening | None:
        return self.positions.get(board.epd())

    def classify(self, initial_fen: str | None, moves: list[str]) -> Opening | None:
        """Name of the deepest named position along a game's moves.
        Games from a set-up position are only named if they reach a book position."""
        board = chess.Board(initial_fen) if initial_fen else chess.Board()
        best = self.lookup(board) if initial_fen else None
        for ply, uci in enumerate(moves):
            if ply >= MAX_SCAN_PLIES:
                break
            try:
                board.push_uci(uci)
            except ValueError:
                break
            found = self.lookup(board)
            if found is not None:
                best = found
        return best


book = OpeningBook()


def name_opening(record: GameRecord) -> None:
    """Name a game's opening from the book (consistent names across sources);
    keep the source's own name when the book does not know the position."""
    opening = book.classify(record.initial_fen, record.moves_uci.split())
    if opening is not None:
        record.eco, record.opening = opening.eco, opening.name
    record.opening_version = BOOK_VERSION
