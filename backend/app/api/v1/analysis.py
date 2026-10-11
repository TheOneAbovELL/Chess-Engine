"""Positions, PGN parsing, one-shot analysis, play, comparison and the live
analysis WebSocket."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any
from urllib.parse import urlparse

import chess
from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.api.deps import container, current_user, rate_key
from app.core.container import Container
from app.core.errors import AppError
from app.services.auth import LOCAL_USER, SESSION_COOKIE, CurrentUser
from app.services.chess.openings import book
from app.services.chess.pgn import game_tree, parse_single_game
from app.services.chess.positions import board_from_request, position_status
from app.services.engine.runtime import StopSignal
from app.services.engine.types import AnalysisSnapshot

from .schemas import (
    AnalyzeRequest,
    BestMoveRequest,
    CompareRequest,
    CompareResult,
    LegalMove,
    PgnParseResponse,
    PgnText,
    PositionInfo,
    PositionRequest,
    UciMove,
)

router = APIRouter()
log = logging.getLogger("chesslab.api.analysis")
MAX_LIVE_PER_USER = 4
MAX_LIVE_TOTAL = 200


@router.post("/positions/validate", response_model=PositionInfo, summary="Validate a position and list legal moves")
def validate_position(body: PositionRequest) -> PositionInfo:
    board = board_from_request(body.fen, body.moves)
    status = position_status(board)
    return PositionInfo(
        fen=board.fen(),
        turn="white" if board.turn == chess.WHITE else "black",
        is_check=status.is_check,
        is_game_over=status.is_game_over,
        outcome=status.outcome,
        result=status.result,
        can_claim_draw=status.can_claim_draw,
        legal_moves=[LegalMove(uci=m.uci(), san=board.san(m)) for m in board.legal_moves],
    )


@router.get("/openings/classify", summary="Opening name for a line of moves (Lichess chess-openings, CC0)")
def classify_opening(
    fen: str | None = Query(None, max_length=100),
    moves: list[UciMove] = Query(default_factory=list, max_length=80),
) -> dict[str, Any]:
    board_from_request(fen, moves)  # validates the line
    opening = book.classify(fen, list(moves))
    return {"eco": opening.eco, "name": opening.name} if opening else {"eco": None, "name": None}


@router.post("/pgn/parse", response_model=PgnParseResponse, summary="Parse a PGN (first game) into a move tree")
def parse_pgn(body: PgnText, c: Container = Depends(container)) -> PgnParseResponse:
    if len(body.pgn.encode("utf-8")) > c.settings.max_pgn_bytes:
        raise AppError("PGN is too large.", code="pgn_too_large", status_code=413)
    game, count = parse_single_game(body.pgn)
    return PgnParseResponse(headers=dict(game.headers), nodes=game_tree(game), games_in_text=count)


@router.post("/analysis", response_model=AnalysisSnapshot, summary="Analyse a position (bounded, waits for the result)")
async def analyse(
    body: AnalyzeRequest,
    request: Request,
    c: Container = Depends(container),
    user: CurrentUser = Depends(current_user),
) -> AnalysisSnapshot:
    c.limiter.check(rate_key(request, user))
    board = board_from_request(body.fen, body.moves)
    limits = c.analysis.limits(body.depth or (None if body.movetime_ms else 18), body.movetime_ms, live=False)
    return await c.analysis.analyse(board, body.engine, limits, c.analysis.multipv(body.multipv), owner=user.id)


@router.post("/analysis/best-move", response_model=AnalysisSnapshot, summary="Engine move for play mode")
async def best_move(
    body: BestMoveRequest,
    request: Request,
    c: Container = Depends(container),
    user: CurrentUser = Depends(current_user),
) -> AnalysisSnapshot:
    c.limiter.check(rate_key(request, user))
    board = board_from_request(body.fen, body.moves)
    return await c.analysis.best_move(
        board, body.engine, level=body.level, depth=body.depth, movetime_ms=body.movetime_ms, owner=user.id
    )


@router.post("/analysis/compare", response_model=list[CompareResult], summary="Run engines on the same position")
async def compare(
    body: CompareRequest,
    request: Request,
    c: Container = Depends(container),
    user: CurrentUser = Depends(current_user),
) -> list[dict[str, Any]]:
    c.limiter.check(rate_key(request, user))
    board = board_from_request(body.fen, body.moves)
    limits = c.analysis.limits(body.depth or (None if body.movetime_ms else 4), body.movetime_ms or 10_000, live=False)
    return await c.analysis.compare(board, list(dict.fromkeys(body.engines)), limits, body.multipv, owner=user.id)


def _origin_allowed(ws: WebSocket, allowed: list[str]) -> bool:
    """Browsers always send Origin on WebSocket upgrades; reject foreign pages
    (cross-site WebSocket hijacking). Non-browser clients send none."""
    origin = ws.headers.get("origin")
    if not origin:
        return True
    host = ws.headers.get("host", "")
    return origin in allowed or urlparse(origin).netloc == host


async def _refuse(ws: WebSocket, code: str, message: str, close_code: int) -> None:
    await ws.accept()
    await ws.send_json({"type": "error", "request_id": None, "code": code, "message": message})
    await ws.close(code=close_code)


@router.websocket("/analysis/live")
async def live_analysis(ws: WebSocket) -> None:
    """Live analysis stream.

    Client messages: ``{"type": "start", "request_id": "...", <AnalyzeRequest fields>}``
    and ``{"type": "stop"}``. Server messages: ``update`` (intermediate
    snapshot), ``done`` (final snapshot) and ``error`` - each with the
    ``request_id`` it belongs to. Starting a new analysis stops the previous one.
    """
    c: Container = ws.app.state.container
    if not _origin_allowed(ws, c.settings.cors_origins):
        await ws.close(code=1008)
        return
    user: CurrentUser | None = LOCAL_USER
    if c.settings.multi_user:
        user = await asyncio.to_thread(c.auth.resolve, ws.cookies.get(SESSION_COOKIE))
    if user is None:
        await _refuse(ws, "auth_required", "Please sign in.", 4401)
        return
    if c.live_connections.get(user.id, 0) >= MAX_LIVE_PER_USER or c.live_total >= MAX_LIVE_TOTAL:
        await _refuse(ws, "too_many_connections", "Too many live analysis connections.", 1013)
        return
    await ws.accept()
    c.live_connections[user.id] = c.live_connections.get(user.id, 0) + 1
    outgoing: asyncio.Queue[tuple[str, str | None, Any]] = asyncio.Queue()
    current: asyncio.Task[None] | None = None
    current_stop: StopSignal | None = None
    key = f"user:{user.id}" if user is not LOCAL_USER else f"ip:{ws.client.host if ws.client else 'unknown'}"

    async def sender() -> None:
        while True:
            batch = [await outgoing.get()]
            while not outgoing.empty():
                batch.append(outgoing.get_nowait())
            # Coalesce consecutive updates for the same request: only the newest matters.
            coalesced: list[tuple[str, str | None, Any]] = []
            for item in batch:
                if coalesced and item[0] == "update" and coalesced[-1][0] == "update" and coalesced[-1][1] == item[1]:
                    coalesced[-1] = item
                else:
                    coalesced.append(item)
            for kind, request_id, payload in coalesced:
                message: dict[str, Any] = {"type": kind, "request_id": request_id}
                if isinstance(payload, AnalysisSnapshot):
                    message["snapshot"] = payload.model_dump(mode="json")
                else:
                    message.update(payload)
                await ws.send_json(message)

    async def run(request_id: str | None, req: AnalyzeRequest, stop: StopSignal) -> None:
        try:
            board = board_from_request(req.fen, req.moves)
            limits = c.analysis.limits(req.depth, req.movetime_ms, live=True)
            final = await c.analysis.analyse(
                board,
                req.engine,
                limits,
                c.analysis.multipv(req.multipv),
                owner=user.id,
                on_update=lambda snap: outgoing.put_nowait(("update", request_id, snap)),
                stop=stop,
            )
            outgoing.put_nowait(("done", request_id, final))
        except AppError as exc:
            outgoing.put_nowait(("error", request_id, {"code": exc.code, "message": exc.message}))
        except Exception:
            log.exception("live analysis failed")
            outgoing.put_nowait(
                ("error", request_id, {"code": "internal_error", "message": "Analysis failed unexpectedly."})
            )

    send_task = asyncio.create_task(sender())
    try:
        while True:
            raw = await ws.receive_text()
            try:
                message = json.loads(raw)
            except ValueError:
                message = None
            kind = message.get("type") if isinstance(message, dict) else None
            if kind == "stop":
                if current_stop is not None:
                    current_stop.request()
                continue
            if kind != "start":
                outgoing.put_nowait(("error", None, {"code": "bad_message", "message": "Unknown message type."}))
                continue
            assert isinstance(message, dict)
            request_id = str(message.get("request_id") or "")[:64] or None
            try:
                c.limiter.check(key)
                req = AnalyzeRequest.model_validate(
                    {k: v for k, v in message.items() if k not in ("type", "request_id")}
                )
            except AppError as exc:
                outgoing.put_nowait(("error", request_id, {"code": exc.code, "message": exc.message}))
                continue
            except ValidationError as exc:
                outgoing.put_nowait(
                    ("error", request_id, {"code": "validation_error", "message": str(exc.errors()[0]["msg"])})
                )
                continue
            if current_stop is not None:
                current_stop.request()
            if current is not None:
                with contextlib.suppress(Exception):
                    await current
            current_stop = StopSignal()
            current = asyncio.create_task(run(request_id, req, current_stop))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        remaining = c.live_connections.get(user.id, 1) - 1
        if remaining > 0:
            c.live_connections[user.id] = remaining
        else:
            c.live_connections.pop(user.id, None)
        if current_stop is not None:
            current_stop.request()
        if current is not None:
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await asyncio.wait_for(current, timeout=10)
        send_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await send_task
