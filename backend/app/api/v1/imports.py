"""Chess.com / Lichess account lookup and game-history imports."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, Path, Query, Request, status

from app.api.deps import container, current_user, rate_key
from app.core.container import Container
from app.core.errors import AppError, InvalidInputError, NotFoundError
from app.services.auth import CurrentUser
from app.services.providers.base import ChessHistoryProvider, ImportParams, ProviderError, validate_username

from .schemas import ImportJobOut, ProviderUserOut

router = APIRouter()

PROVIDER_INFO = {
    "chesscom": {
        "docs": "https://www.chess.com/news/view/published-data-api",
        "notes": [
            "Uses Chess.com's free Published-Data API. No password or API key is needed.",
            "Only public games are available. Chess.com may cache archives for up to 12-24 hours, "
            "so a game you just finished can take a while to appear.",
        ],
    },
    "lichess": {
        "docs": "https://lichess.org/api#tag/Games/operation/apiGamesUser",
        "notes": [
            "Uses Lichess's free public API. No password or token is needed for public games.",
            "Lichess streams about 20 games per second to anonymous clients, so large imports take a little time.",
        ],
    },
}


def _provider(c: Container, provider: str) -> ChessHistoryProvider:
    found = c.providers.get(provider)
    if found is None:
        raise NotFoundError(f"Unknown provider '{provider}'.")
    return found


def _username(username: str) -> str:
    try:
        return validate_username(username)
    except ValueError as exc:
        raise InvalidInputError(str(exc), code="invalid_username") from exc


def _provider_error(exc: ProviderError) -> AppError:
    status_code = {
        "not_found": 404,
        "closed": 404,
        "rate_limited": 429,
        "network": 502,
        "server": 502,
        "bad_response": 502,
    }.get(exc.kind, 502)
    return AppError(exc.message, code=f"provider_{exc.kind}", status_code=status_code)


@router.get("/providers", summary="Supported game-history providers")
def providers(c: Container = Depends(container)) -> list[dict[str, Any]]:
    return [{"id": p.name, "name": p.display_name, **PROVIDER_INFO.get(p.name, {})} for p in c.providers.values()]


@router.get("/providers/{provider}/users/{username}", response_model=ProviderUserOut, summary="Check a public account")
async def lookup(
    request: Request,
    provider: str,
    username: str = Path(max_length=30),
    c: Container = Depends(container),
    user: CurrentUser = Depends(current_user),
) -> dict[str, Any]:
    c.lookup_limiter.check(rate_key(request, user))
    p = _provider(c, provider)
    try:
        account = await p.lookup_user(_username(username))
    except ProviderError as exc:
        raise _provider_error(exc) from exc
    return asdict(account)


@router.get("/providers/{provider}/users/{username}/preview", summary="A few recent public games (not imported)")
async def preview(
    request: Request,
    provider: str,
    username: str = Path(max_length=30),
    limit: int = Query(10, ge=1, le=25),
    c: Container = Depends(container),
    user: CurrentUser = Depends(current_user),
) -> list[dict[str, Any]]:
    c.lookup_limiter.check(rate_key(request, user))
    p = _provider(c, provider)
    try:
        return await p.preview(_username(username), limit)
    except ProviderError as exc:
        raise _provider_error(exc) from exc


@router.post(
    "/imports", response_model=ImportJobOut, status_code=status.HTTP_202_ACCEPTED, summary="Start an import job"
)
def start_import(
    body: ImportParams, c: Container = Depends(container), user: CurrentUser = Depends(current_user)
) -> dict[str, Any]:
    return c.imports.create_job(user.id, body)


@router.post(
    "/imports/refresh-all",
    response_model=list[ImportJobOut],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Fetch new games for every linked account",
)
def refresh_all(c: Container = Depends(container), user: CurrentUser = Depends(current_user)) -> list[dict[str, Any]]:
    jobs = []
    for account in c.store.preferences(user.id).accounts:
        try:
            jobs.append(
                c.imports.create_job(
                    user.id,
                    ImportParams(
                        provider=account.provider,
                        username=account.username,
                        mode="refresh",
                        max_games=c.settings.max_import_games,
                    ),
                )
            )
        except AppError:
            continue  # e.g. an import for this account is already running
    return jobs


@router.get("/imports", response_model=list[ImportJobOut], summary="Recent import jobs")
def list_imports(
    limit: int = Query(20, ge=1, le=100), c: Container = Depends(container), user: CurrentUser = Depends(current_user)
) -> list[dict[str, Any]]:
    return c.imports.list_jobs(user.id, limit)


@router.get("/imports/{job_id}", response_model=ImportJobOut, summary="Import job status")
def get_import(
    job_id: str = Path(max_length=36), c: Container = Depends(container), user: CurrentUser = Depends(current_user)
) -> dict[str, Any]:
    return c.imports.get(user.id, job_id)


@router.post("/imports/{job_id}/cancel", response_model=ImportJobOut)
def cancel_import(
    job_id: str = Path(max_length=36), c: Container = Depends(container), user: CurrentUser = Depends(current_user)
) -> dict[str, Any]:
    return c.imports.cancel(user.id, job_id)


@router.post("/imports/{job_id}/retry", response_model=ImportJobOut, status_code=status.HTTP_202_ACCEPTED)
def retry_import(
    job_id: str = Path(max_length=36), c: Container = Depends(container), user: CurrentUser = Depends(current_user)
) -> dict[str, Any]:
    return c.imports.retry(user.id, job_id)
