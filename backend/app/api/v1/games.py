"""Game library, PGN import/export and reviews."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import container, current_user, game_filters
from app.core.container import Container
from app.core.errors import InvalidInputError
from app.repositories.games import GameFilters
from app.services.auth import CurrentUser

from .schemas import (
    BatchReviewRequest,
    GameDetail,
    GamePage,
    IdsRequest,
    PgnImportRequest,
    PgnText,
    ReviewRequest,
    UploadSummaryOut,
)

router = APIRouter()
PGN_MEDIA_TYPE = "application/x-chess-pgn"


def _attachment(filename: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{filename}"'}


@router.get("/games", response_model=GamePage, summary="List stored games (filtered, paginated)")
def list_games(
    filters: GameFilters = Depends(game_filters),
    sort: Literal["played_desc", "played_asc", "imported_desc", "rating_desc", "length_desc"] = "played_desc",
    page: int = Query(1, ge=1, le=100_000),
    page_size: int = Query(25, ge=1, le=100),
    c: Container = Depends(container),
    user: CurrentUser = Depends(current_user),
) -> dict[str, Any]:
    items, total = c.games.list_games(user.id, filters, sort=sort, page=page, page_size=page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/games/owners", summary="Imported accounts and their game counts")
def owners(c: Container = Depends(container), user: CurrentUser = Depends(current_user)) -> list[dict[str, Any]]:
    return c.games.owners(user.id)


@router.get("/games/export.pgn", summary="Export filtered games as one PGN file")
def export_games(
    filters: GameFilters = Depends(game_filters),
    c: Container = Depends(container),
    user: CurrentUser = Depends(current_user),
) -> Response:
    return Response(
        c.games.export(user.id, filters), media_type=PGN_MEDIA_TYPE, headers=_attachment("chesslab-games.pgn")
    )


@router.post("/games/import-pgn", response_model=UploadSummaryOut, summary="Import games from PGN text")
def import_pgn(
    body: PgnImportRequest, c: Container = Depends(container), user: CurrentUser = Depends(current_user)
) -> Any:
    return c.games.import_pgn(user.id, body.pgn, owner=body.owner)


@router.post(
    "/games/save",
    response_model=UploadSummaryOut,
    status_code=status.HTTP_201_CREATED,
    summary="Save a game played in ChessLab",
)
def save_game(
    body: PgnImportRequest, c: Container = Depends(container), user: CurrentUser = Depends(current_user)
) -> Any:
    return c.games.import_pgn(user.id, body.pgn, owner=body.owner, source_override="local")


@router.post("/games/delete", summary="Delete several games")
def delete_games(
    body: IdsRequest, c: Container = Depends(container), user: CurrentUser = Depends(current_user)
) -> dict[str, int]:
    return {"deleted": c.games.delete_many(user.id, body.ids)}


@router.get("/games/{game_id}", response_model=GameDetail, summary="One game with moves and headers")
def get_game(
    game_id: int, c: Container = Depends(container), user: CurrentUser = Depends(current_user)
) -> dict[str, Any]:
    return c.games.detail(user.id, game_id)


@router.get("/games/{game_id}/pgn", summary="Download one game as PGN")
def get_game_pgn(
    game_id: int, c: Container = Depends(container), user: CurrentUser = Depends(current_user)
) -> Response:
    pgn, filename = c.games.pgn(user.id, game_id)
    return Response(pgn, media_type=PGN_MEDIA_TYPE, headers=_attachment(filename))


@router.delete("/games/{game_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a game (and its reviews)")
def delete_game(game_id: int, c: Container = Depends(container), user: CurrentUser = Depends(current_user)) -> Response:
    c.games.delete(user.id, game_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/games/{game_id}/review", status_code=status.HTTP_202_ACCEPTED, summary="Queue an engine review of a game"
)
def start_review(
    game_id: int, body: ReviewRequest, c: Container = Depends(container), user: CurrentUser = Depends(current_user)
) -> dict[str, Any]:
    return c.reviews.enqueue(
        user.id,
        game_id,
        engine_id=body.engine,
        depth=body.depth,
        movetime_ms=body.movetime_ms,
        multipv=body.multipv,
        force=body.force,
    )


@router.get("/games/{game_id}/review", summary="Latest review of a game with per-move results")
def latest_review(
    game_id: int, c: Container = Depends(container), user: CurrentUser = Depends(current_user)
) -> dict[str, Any] | None:
    return c.reviews.latest_for_game(user.id, game_id)


@router.post("/reviews/batch", status_code=status.HTTP_202_ACCEPTED, summary="Queue reviews for several games")
def batch_review(
    body: BatchReviewRequest, c: Container = Depends(container), user: CurrentUser = Depends(current_user)
) -> list[dict[str, Any]]:
    return c.reviews.enqueue_many(
        user.id,
        body.game_ids,
        engine_id=body.engine,
        depth=body.depth,
        movetime_ms=body.movetime_ms,
        multipv=body.multipv,
        force=body.force,
    )


@router.get("/reviews/queue", summary="Queued and running reviews")
def review_queue(c: Container = Depends(container), user: CurrentUser = Depends(current_user)) -> list[dict[str, Any]]:
    return c.reviews.queue(user.id)


@router.get("/reviews/{review_id}", summary="Review status (and optionally positions)")
def get_review(
    review_id: int,
    positions: bool = False,
    c: Container = Depends(container),
    user: CurrentUser = Depends(current_user),
) -> dict[str, Any]:
    return c.reviews.get(user.id, review_id, with_positions=positions)


@router.post("/reviews/{review_id}/cancel", summary="Cancel a queued or running review")
def cancel_review(
    review_id: int, c: Container = Depends(container), user: CurrentUser = Depends(current_user)
) -> dict[str, Any]:
    return c.reviews.cancel(user.id, review_id)


@router.post("/reviews/{review_id}/retry", summary="Resume a failed or cancelled review")
def retry_review(
    review_id: int, c: Container = Depends(container), user: CurrentUser = Depends(current_user)
) -> dict[str, Any]:
    return c.reviews.retry(user.id, review_id)


@router.post("/reviews/{review_id}/reclassify", summary="Re-label moves with the current thresholds")
def reclassify(
    review_id: int, c: Container = Depends(container), user: CurrentUser = Depends(current_user)
) -> dict[str, Any]:
    return c.reviews.reclassify(user.id, review_id)


@router.post("/pgn/validate", summary="Check PGN text without storing it")
def validate_pgn(body: PgnText) -> dict[str, Any]:
    from app.services.chess.pgn import ParseFailure, iter_pgn_games

    ok = failed = 0
    errors: list[dict[str, Any]] = []
    for item in iter_pgn_games(body.pgn, 2000):
        if isinstance(item, ParseFailure):
            failed += 1
            if len(errors) < 20:
                errors.append({"index": item.index, "error": item.error})
        else:
            ok += 1
    if ok == 0 and failed == 0:
        raise InvalidInputError("No games found in the text.", code="invalid_pgn")
    return {"valid_games": ok, "invalid_games": failed, "errors": errors}
