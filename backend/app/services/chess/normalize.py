"""GameNormalizationService: turn a parsed PGN game (plus optional provider
metadata) into a uniform :class:`GameRecord` ready to persist.

Provider-specific knowledge lives in the providers; this module only knows
generic PGN conventions and how to recognise Chess.com / Lichess links so that
an uploaded PGN deduplicates against the same game imported through the API.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import chess
import chess.pgn

from .pgn import MalformedGameError, export_game

CHESSCOM_LINK_RE = re.compile(r"chess\.com/(?:game/)?(live|daily)/(?:game/)?(\d+)", re.IGNORECASE)
LICHESS_LINK_RE = re.compile(r"lichess\.org/([A-Za-z0-9]{8})(?:[A-Za-z0-9]{4})?(?:/|$|\?|#)", re.IGNORECASE)
VALID_RESULTS = {"1-0", "0-1", "1/2-1/2", "*"}
STANDARD_VARIANTS = {"", "standard", "chess", "from position"}
TIME_CLASSES = ("ultrabullet", "bullet", "blitz", "rapid", "classical", "correspondence", "unknown")


class UnsupportedGameError(ValueError):
    """The game is valid but outside what ChessLab analyses (e.g. a variant)."""


@dataclass
class GameRecord:
    source: str
    external_id: str
    white: str
    black: str
    result: str
    pgn: str
    moves_uci: str
    ply_count: int
    played_at: datetime | None = None
    white_elo: int | None = None
    black_elo: int | None = None
    termination: str | None = None
    time_control: str | None = None
    time_class: str = "unknown"
    rated: bool | None = None
    variant: str = "standard"
    eco: str | None = None
    opening: str | None = None
    event: str | None = None
    url: str | None = None
    initial_fen: str | None = None
    owner_username: str | None = None
    user_color: str | None = None
    user_result: str | None = None
    opening_version: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_model_kwargs(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data.pop("extra")
        return data


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse_pgn_datetime(headers: chess.pgn.Headers) -> datetime | None:
    """Prefer UTCDate/UTCTime; fall back to Date/Time (assumed UTC)."""
    for date_key, time_key in (("UTCDate", "UTCTime"), ("Date", "Time")):
        date = headers.get(date_key, "")
        if not re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", date):
            continue
        time = headers.get(time_key, "")
        try:
            if re.fullmatch(r"\d{2}:\d{2}:\d{2}", time):
                return datetime.strptime(f"{date} {time}", "%Y.%m.%d %H:%M:%S").replace(tzinfo=UTC)
            return datetime.strptime(date, "%Y.%m.%d").replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def time_class_from_control(time_control: str | None) -> str:
    """Classify a PGN TimeControl using Lichess's published formula:
    estimated duration = base + 40 * increment (seconds)."""
    if not time_control or time_control in {"?"}:
        return "unknown"
    if time_control == "-" or "/" in time_control:
        return "correspondence"
    match = re.fullmatch(r"(\d+)(?:\+(\d+))?", time_control.strip())
    if not match:
        return "unknown"
    base, inc = int(match.group(1)), int(match.group(2) or 0)
    total = base + 40 * inc
    if total < 30:
        return "ultrabullet"
    if total < 180:
        return "bullet"
    if total < 480:
        return "blitz"
    if total < 1500:
        return "rapid"
    return "classical"


def opening_from_eco_url(url: str | None) -> str | None:
    """Chess.com puts the opening name in the ECOUrl slug, e.g.
    ``.../openings/Sicilian-Defense-Closed-Variation...6.exd5`` ->
    ``Sicilian Defense Closed Variation``."""
    if not url or "/openings/" not in url:
        return None
    slug = url.rsplit("/openings/", 1)[1].split("?")[0]
    slug = slug.split("...")[0]
    words = []
    for token in slug.split("-"):
        if re.match(r"^\d+(\.|$)", token):  # move numbers ("4.Be3" or a bare "2") start the move suffix
            break
        if token:
            words.append(token)
    name = " ".join(words).strip()
    return name[:200] or None


def detect_source(headers: chess.pgn.Headers) -> tuple[str, str] | None:
    """Recognise Chess.com / Lichess games from their Link/Site headers."""
    for key in ("Link", "Site", "GameId"):
        value = headers.get(key, "")
        match = CHESSCOM_LINK_RE.search(value)
        if match:
            return "chesscom", f"{match.group(1).lower()}/{match.group(2)}"
        match = LICHESS_LINK_RE.search(value + "/")
        if match:
            return "lichess", match.group(1)
    game_id = headers.get("GameId", "")
    if re.fullmatch(r"[A-Za-z0-9]{8}", game_id) and "lichess" in headers.get("Site", "").lower():
        return "lichess", game_id
    return None


def fingerprint(white: str, black: str, date: str, result: str, initial_fen: str | None, moves_uci: str) -> str:
    raw = "|".join([white.lower(), black.lower(), date, result, initial_fen or "", moves_uci])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def user_perspective(white: str, black: str, result: str, owner: str | None) -> tuple[str | None, str | None]:
    if not owner:
        return None, None
    owner_l = owner.lower()
    if white.lower() == owner_l:
        color = "white"
    elif black.lower() == owner_l:
        color = "black"
    else:
        return None, None
    if result == "1/2-1/2":
        return color, "draw"
    if result == "1-0":
        return color, "win" if color == "white" else "loss"
    if result == "0-1":
        return color, "win" if color == "black" else "loss"
    return color, None


def normalize_game(
    game: chess.pgn.Game,
    *,
    owner: str | None = None,
    source: str | None = None,
    external_id: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> GameRecord:
    """Validate and normalise a parsed game.

    ``source``/``external_id`` are given by providers; otherwise they are
    detected from the headers, falling back to ``("pgn", fingerprint)``.
    ``overrides`` lets providers supply authoritative metadata (e.g. the
    Chess.com ``time_class`` or exact end time).
    """
    if game.errors:
        raise MalformedGameError(str(game.errors[0]))
    headers = game.headers
    variant = headers.get("Variant", "").strip().lower()
    if variant not in STANDARD_VARIANTS:
        raise UnsupportedGameError(f"Variant '{headers.get('Variant')}' is not supported (standard chess only).")

    board = game.board()
    initial_fen = None if board.fen() == chess.STARTING_FEN else board.fen()
    moves: list[str] = []
    for move in game.mainline_moves():
        if move not in board.legal_moves:  # defensive: python-chess already checks
            raise MalformedGameError(f"Illegal move {move.uci()} in game.")
        moves.append(move.uci())
        board.push(move)
    moves_uci = " ".join(moves)

    white = (headers.get("White") or "?").strip()[:64] or "?"
    black = (headers.get("Black") or "?").strip()[:64] or "?"
    result = headers.get("Result", "*").strip()
    if result not in VALID_RESULTS:
        result = "*"
    if result == "*" and board.is_game_over():
        result = board.result()

    if source is None or external_id is None:
        detected = detect_source(headers)
        if detected:
            source, external_id = detected
        else:
            source = "pgn"
            external_id = fingerprint(white, black, headers.get("Date", "?"), result, initial_fen, moves_uci)

    time_control = (headers.get("TimeControl") or "").strip() or None
    event = (headers.get("Event") or "").strip()[:160] or None
    rated: bool | None = None
    if event:
        lowered = event.lower()
        if lowered.startswith("rated"):
            rated = True
        elif lowered.startswith("casual"):
            rated = False

    url = headers.get("Link") or (headers.get("Site") if headers.get("Site", "").startswith("http") else None)
    opening = headers.get("Opening") or opening_from_eco_url(headers.get("ECOUrl"))
    eco = headers.get("ECO")
    eco = eco if eco and re.fullmatch(r"[A-E]\d\d", eco) else None

    record = GameRecord(
        source=source,
        external_id=external_id,
        white=white,
        black=black,
        result=result,
        pgn=export_game(game),
        moves_uci=moves_uci,
        ply_count=len(moves),
        played_at=parse_pgn_datetime(headers),
        white_elo=_int_or_none(headers.get("WhiteElo")),
        black_elo=_int_or_none(headers.get("BlackElo")),
        termination=(headers.get("Termination") or "").strip()[:160] or None,
        time_control=time_control[:32] if time_control else None,
        time_class=time_class_from_control(time_control),
        rated=rated,
        eco=eco,
        opening=opening[:200] if opening else None,
        event=event,
        url=url[:255] if url else None,
        initial_fen=initial_fen,
    )
    for key, value in (overrides or {}).items():
        if value is not None:
            setattr(record, key, value)
    if record.time_class not in TIME_CLASSES:
        record.time_class = "unknown"
    record.owner_username = owner.lower() if owner else None
    record.user_color, record.user_result = user_perspective(record.white, record.black, record.result, owner)
    return record
