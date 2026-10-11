"""Defensive PGN parsing.

python-chess is tolerant: it records problems (illegal moves, bad SAN) in
``game.errors`` instead of raising. We turn those into explicit failures so a
malformed game is reported, never silently truncated and stored.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import chess
import chess.pgn

from app.core.errors import InvalidInputError

MAX_TREE_NODES = 5000
_COMMAND_RE = re.compile(r"\[%[^\]]*\]")


class MalformedGameError(ValueError):
    pass


@dataclass
class ParsedGame:
    game: chess.pgn.Game
    index: int  # position in the uploaded file (0-based)


@dataclass
class ParseFailure:
    index: int
    error: str
    headers: dict[str, str] = field(default_factory=dict)


def iter_pgn_games(text: str, max_games: int) -> Iterator[ParsedGame | ParseFailure]:
    """Yield parsed games (or failures) from a multi-game PGN string."""
    stream = io.StringIO(text)
    index = 0
    while index < max_games:
        try:
            game = chess.pgn.read_game(stream)
        except Exception as exc:  # python-chess raises only on truly broken input
            yield ParseFailure(index, f"Unreadable PGN: {exc}")
            return
        if game is None:
            return
        if game.errors:
            yield ParseFailure(index, f"Invalid game: {game.errors[0]}", dict(game.headers))
        elif not _has_content(game):
            yield ParseFailure(index, "Game has no moves and no position.", dict(game.headers))
        else:
            yield ParsedGame(game, index)
        index += 1


def _has_content(game: chess.pgn.Game) -> bool:
    return bool(game.variations) or "FEN" in game.headers


def parse_single_game(text: str) -> tuple[chess.pgn.Game, int]:
    """Parse the first game of a PGN (for the analysis board). Returns the game
    and the number of games found in the text (bounded)."""
    first: chess.pgn.Game | None = None
    count = 0
    for item in iter_pgn_games(text, max_games=1000):
        count += 1
        if first is None:
            if isinstance(item, ParseFailure):
                raise InvalidInputError(item.error, code="invalid_pgn")
            first = item.game
    if first is None:
        raise InvalidInputError("No game found in the PGN text.", code="invalid_pgn")
    return first, count


def clean_comment(comment: str) -> str:
    """Remove machine commands such as ``[%clk 0:01:00]`` from a comment."""
    return _COMMAND_RE.sub("", comment).strip()


def game_tree(game: chess.pgn.Game) -> list[dict[str, Any]]:
    """Flatten a game (with variations) into nodes for the frontend.

    Node 0 is the starting position. ``children[0]`` of each node is the main
    continuation; further children are variations.
    """
    nodes: list[dict[str, Any]] = []

    def add(node: chess.pgn.GameNode, parent: int | None, ply: int) -> int:
        if len(nodes) >= MAX_TREE_NODES:
            raise InvalidInputError("The game has too many moves/variations.", code="pgn_too_large")
        board = node.board()
        entry: dict[str, Any] = {
            "id": len(nodes),
            "parent": parent,
            "ply": ply,
            "fen": board.fen(),
            "san": None,
            "uci": None,
            "comment": clean_comment(node.comment) or None,
            "nags": sorted(node.nags),
            "clock": node.clock() if parent is not None else None,
            "children": [],
        }
        if parent is not None and node.move is not None:
            parent_board = node.parent.board() if node.parent else chess.Board()
            entry["san"] = parent_board.san(node.move)
            entry["uci"] = node.move.uci()
        nodes.append(entry)
        node_id = entry["id"]
        for child in node.variations:
            child_id = add(child, node_id, ply + 1)
            entry["children"].append(child_id)
        return int(node_id)

    add(game, None, 0)
    return nodes


def mainline_moves(game: chess.pgn.Game) -> list[dict[str, Any]]:
    """Mainline as a list of {ply, san, uci, fen (after), clock}."""
    board = game.board()
    result = []
    for ply, node in enumerate(game.mainline(), start=1):
        move = node.move
        san = board.san(move)
        board.push(move)
        result.append({"ply": ply, "san": san, "uci": move.uci(), "fen": board.fen(), "clock": node.clock()})
    return result


def export_game(game: chess.pgn.Game) -> str:
    exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
    return game.accept(exporter)
