"""Builders for realistic provider payloads (all games are legal by construction)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import chess
import chess.pgn

OPENINGS = [
    ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6"],
    ["d4", "d5", "c4", "e6", "Nc3", "Nf6", "Bg5", "Be7"],
    ["e4", "c5", "Nf3", "d6", "d4", "cxd4", "Nxd4", "Nf6"],
    ["c4", "e5", "Nc3", "Nf6", "g3", "d5", "cxd5", "Nxd5"],
]
SCHOLARS_MATE = ["e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6", "Qxf7#"]


def make_pgn(moves: list[str], headers: dict[str, str], clocks: list[str] | None = None) -> str:
    game = chess.pgn.Game()
    for key, value in headers.items():
        game.headers[key] = value
    node: chess.pgn.GameNode = game
    for i, san in enumerate(moves):
        node = node.add_variation(node.board().parse_san(san))
        if clocks:
            node.comment = f"[%clk {clocks[i % len(clocks)]}]"
    if "Result" not in headers:
        game.headers["Result"] = node.board().result() if node.board().is_game_over() else "*"
    return str(game)


def chesscom_game(
    game_id: int,
    white: str,
    black: str,
    result: str,
    end_time: int,
    *,
    moves: list[str] | None = None,
    time_class: str = "blitz",
    rules: str = "chess",
    rated: bool = True,
    pgn: str | None = None,
) -> dict[str, Any]:
    moves = moves or OPENINGS[game_id % len(OPENINGS)]
    url = f"https://www.chess.com/game/live/{game_id}"
    day = datetime.fromtimestamp(end_time, UTC)
    headers = {
        "Event": "Live Chess",
        "Site": "Chess.com",
        "Date": day.strftime("%Y.%m.%d"),
        "White": white,
        "Black": black,
        "Result": result,
        "UTCDate": day.strftime("%Y.%m.%d"),
        "UTCTime": day.strftime("%H:%M:%S"),
        "WhiteElo": "1500",
        "BlackElo": "1480",
        "TimeControl": "180+2",
        "ECO": "C60",
        "ECOUrl": "https://www.chess.com/openings/Ruy-Lopez-Opening-Morphy-Defense...4.Ba4-Nf6",
        "Termination": f"{white} won by resignation" if result == "1-0" else "Game drawn by agreement",
        "Link": url,
    }
    white_result = {"1-0": "win", "0-1": "resigned", "1/2-1/2": "agreed"}[result]
    black_result = {"1-0": "resigned", "0-1": "win", "1/2-1/2": "agreed"}[result]
    return {
        "url": url,
        "pgn": pgn if pgn is not None else make_pgn(moves, headers, clocks=["0:02:58", "0:02:55"]),
        "time_control": "180+2",
        "end_time": end_time,
        "rated": rated,
        "uuid": f"uuid-{game_id}",
        "time_class": time_class,
        "rules": rules,
        "white": {
            "rating": 1500,
            "result": white_result,
            "username": white,
            "@id": f"https://api.chess.com/pub/player/{white.lower()}",
        },
        "black": {
            "rating": 1480,
            "result": black_result,
            "username": black,
            "@id": f"https://api.chess.com/pub/player/{black.lower()}",
        },
    }


def lichess_pgn(
    game_id: str,
    white: str,
    black: str,
    result: str,
    when: datetime,
    *,
    event: str = "rated blitz game",
    variant: str = "Standard",
    moves: list[str] | None = None,
) -> str:
    headers = {
        "Event": event,
        "Site": f"https://lichess.org/{game_id}",
        "Date": when.strftime("%Y.%m.%d"),
        "White": white,
        "Black": black,
        "Result": result,
        "GameId": game_id,
        "UTCDate": when.strftime("%Y.%m.%d"),
        "UTCTime": when.strftime("%H:%M:%S"),
        "WhiteElo": "1720",
        "BlackElo": "1700",
        "Variant": variant,
        "TimeControl": "300+3",
        "ECO": "B90",
        "Opening": "Sicilian Defense: Najdorf Variation",
        "Termination": "Normal",
    }
    return make_pgn(moves or OPENINGS[2], headers, clocks=["0:05:00", "0:04:57"])
