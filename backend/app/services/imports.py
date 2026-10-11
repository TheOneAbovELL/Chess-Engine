"""GameImportService: runs provider imports as persistent background jobs.

Guarantees
----------
* **Idempotent**: games are deduplicated by ``(source, external_id)``, so
  retries, refreshes and resumed jobs never create duplicates.
* **Incremental persistence**: each batch is written in its own transaction
  together with the job counters. An interrupted import keeps everything it
  stored, and its progress numbers match the database.
* **Honest outcome**: ``completed`` only when every discovered game was stored
  or recognised as a duplicate; ``partial`` when some failed; ``failed`` when
  the provider could not be read at all.
"""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import chess.pgn
from sqlalchemy import select, update

from app.core.config import Settings
from app.core.errors import ConflictError, InvalidInputError, NotFoundError
from app.db.base import utcnow
from app.db.session import Database
from app.jobs.worker import BackgroundWorker
from app.models import HttpCacheEntry, ImportJob
from app.models.jobs import ACTIVE_STATUSES, CANCELLED, COMPLETED, FAILED, PARTIAL, QUEUED, RUNNING
from app.repositories.games import GameRepository

from .chess.normalize import UnsupportedGameError, normalize_game
from .chess.pgn import MalformedGameError
from .providers.base import (
    BatchStats,
    ChessHistoryProvider,
    ImportContext,
    ImportParams,
    ProviderBatch,
    ProviderError,
    RawGame,
)
from .settings_store import SettingsStore

log = logging.getLogger("chesslab.imports")
MAX_ERRORS = 50


def job_to_dict(job: ImportJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "provider": job.provider,
        "username": job.username,
        "params": job.params,
        "status": job.status,
        "discovered": job.discovered,
        "imported": job.imported,
        "duplicates": job.duplicates,
        "failed": job.failed,
        "skipped": job.skipped,
        "phase": job.phase,
        "message": job.message,
        "errors": job.errors,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


class _JobContext(ImportContext):
    def __init__(self, service: GameImportService, job_id: str) -> None:
        self.service = service
        self.job_id = job_id

    async def cache_validators(self, url: str) -> tuple[str | None, str | None]:
        def read() -> tuple[str | None, str | None]:
            with self.service.db.session() as session:
                entry = session.get(HttpCacheEntry, url)
                return (entry.etag, entry.last_modified) if entry else (None, None)

        return await asyncio.to_thread(read)

    async def store_validators(self, url: str, etag: str | None, last_modified: str | None) -> None:
        if not etag and not last_modified:
            return

        def write() -> None:
            with self.service.db.session() as session:
                entry = session.get(HttpCacheEntry, url)
                if entry is None:
                    session.add(HttpCacheEntry(url=url, etag=etag, last_modified=last_modified))
                else:
                    entry.etag, entry.last_modified = etag, last_modified

        await asyncio.to_thread(write)

    async def latest_played_at(self, source: str, owner: str) -> datetime | None:
        def read() -> datetime | None:
            with self.service.db.session() as session:
                return GameRepository(session).latest_played_at(source, owner)

        return await asyncio.to_thread(read)

    async def set_phase(self, phase: str) -> None:
        await asyncio.to_thread(self.service._update, self.job_id, phase=phase[:160])

    async def cancel_requested(self) -> bool:
        def read() -> bool:
            with self.service.db.session() as session:
                job = session.get(ImportJob, self.job_id)
                return bool(job and job.cancel_requested)

        return await asyncio.to_thread(read)


class GameImportService(BackgroundWorker[str]):
    name = "import-worker"
    poll_interval_s = 5.0

    def __init__(
        self, db: Database, settings: Settings, providers: dict[str, ChessHistoryProvider], store: SettingsStore
    ) -> None:
        super().__init__()
        self.db = db
        self.settings = settings
        self.providers = providers
        self.store = store

    # -------------------------------------------------------------- enqueue
    def create_job(self, params: ImportParams) -> dict[str, Any]:
        if params.max_games > self.settings.max_import_games:
            raise InvalidInputError(
                f"At most {self.settings.max_import_games} games per import.", code="too_many_games"
            )
        if params.provider not in self.providers:
            raise InvalidInputError(f"Unknown provider '{params.provider}'.", code="unknown_provider")
        with self.db.session() as session:
            active = session.execute(
                select(ImportJob).where(
                    ImportJob.provider == params.provider,
                    ImportJob.username == params.username.lower(),
                    ImportJob.status.in_(ACTIVE_STATUSES),
                )
            ).scalar_one_or_none()
            if active is not None:
                raise ConflictError("An import for this account is already in progress.", code="import_in_progress")
            job = ImportJob(
                id=str(uuid.uuid4()),
                provider=params.provider,
                username=params.username.lower(),
                params=params.model_dump(mode="json"),
                status=QUEUED,
                phase="Waiting to start",
                errors=[],
            )
            session.add(job)
            session.flush()
            result = job_to_dict(job)
        self.notify()
        return result

    def get(self, job_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            job = session.get(ImportJob, job_id)
            if job is None:
                raise NotFoundError("Import job not found.")
            return job_to_dict(job)

    def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.execute(select(ImportJob).order_by(ImportJob.created_at.desc()).limit(limit)).scalars()
            return [job_to_dict(j) for j in rows]

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            job = session.get(ImportJob, job_id)
            if job is None:
                raise NotFoundError("Import job not found.")
            if job.status == QUEUED:
                job.status, job.finished_at, job.message = CANCELLED, utcnow(), "Cancelled before it started."
            elif job.status == RUNNING:
                job.cancel_requested = True
            return job_to_dict(job)

    def retry(self, job_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            job = session.get(ImportJob, job_id)
            if job is None:
                raise NotFoundError("Import job not found.")
            if job.status in ACTIVE_STATUSES:
                raise ConflictError("This import is still running.", code="import_in_progress")
            params = ImportParams.model_validate(job.params)
        return self.create_job(params)

    # --------------------------------------------------------------- worker
    def recover(self) -> None:
        with self.db.session() as session:
            session.execute(
                update(ImportJob)
                .where(ImportJob.status == RUNNING)
                .values(status=QUEUED, phase="Resuming after restart", cancel_requested=False)
            )

    def claim_next(self) -> str | None:
        with self.db.session() as session:
            job = session.execute(
                select(ImportJob).where(ImportJob.status == QUEUED).order_by(ImportJob.created_at.asc()).limit(1)
            ).scalar_one_or_none()
            if job is None:
                return None
            job.status, job.started_at, job.phase = RUNNING, utcnow(), "Starting"
            return job.id

    def mark_crashed(self, job: str) -> None:
        self._update(
            job,
            status=FAILED,
            finished_at=utcnow(),
            message="The import stopped because of an unexpected error. Retry to continue.",
        )

    def _update(self, job_id: str, **values: Any) -> None:
        with self.db.session() as session:
            session.execute(update(ImportJob).where(ImportJob.id == job_id).values(**values))

    async def process(self, job: str) -> None:
        await self.run_job(job)

    async def run_job(self, job_id: str) -> None:
        def load() -> ImportJob | None:
            with self.db.session() as session:
                return session.get(ImportJob, job_id)

        job = await asyncio.to_thread(load)
        if job is None:
            return
        params = ImportParams.model_validate(job.params)
        provider = self.providers[params.provider]
        ctx = _JobContext(self, job_id)
        max_games = min(params.max_games, self.settings.max_import_games)
        log.info("import started", extra={"job": job_id, "provider": params.provider, "user": params.username})
        try:
            if params.provider == "chesscom":  # Lichess checks the account inside fetch()
                await ctx.set_phase("Checking the Chess.com account")
                await provider.lookup_user(params.username)
            async for batch in provider.fetch(params, ctx, max_games):
                batch.stats = await asyncio.to_thread(self._persist_batch, job_id, batch, params.username)
                if batch.on_complete is not None and batch.stats.failed == 0:
                    await batch.on_complete()
                if await ctx.cancel_requested():
                    await asyncio.to_thread(self._finish, job_id, cancelled=True)
                    return
        except ProviderError as exc:
            log.warning("import failed", extra={"job": job_id, "kind": exc.kind})
            await asyncio.to_thread(self._finish, job_id, error=exc.message)
            return
        await asyncio.to_thread(self._finish, job_id)
        await asyncio.to_thread(self.store.remember_account, params.provider, params.username)

    def _normalize(self, raw: RawGame, owner: str) -> Any:
        game = chess.pgn.read_game(io.StringIO(raw.pgn))
        if game is None:
            raise MalformedGameError("Empty PGN.")
        return normalize_game(
            game, owner=owner, source=raw.source, external_id=raw.external_id, overrides=raw.overrides
        )

    def _persist_batch(self, job_id: str, batch: ProviderBatch, owner: str) -> BatchStats:
        stats = BatchStats()
        errors: list[dict[str, str]] = []
        with self.db.session() as session:
            repo = GameRepository(session)
            for raw in batch.games:
                if raw.skip_reason:
                    stats.skipped += 1
                    errors.append({"ref": raw.ref, "error": raw.skip_reason})
                    continue
                if raw.external_id and repo.exists(raw.source, raw.external_id):
                    stats.duplicates += 1  # cheap path: skip parsing known games
                    continue
                try:
                    record = self._normalize(raw, owner)
                except UnsupportedGameError as exc:
                    stats.skipped += 1
                    errors.append({"ref": raw.ref, "error": str(exc)})
                    continue
                except (MalformedGameError, ValueError) as exc:
                    stats.failed += 1
                    errors.append({"ref": raw.ref, "error": f"Could not parse the game: {exc}"})
                    continue
                if repo.insert(record, import_job_id=job_id) is None:
                    stats.duplicates += 1
                else:
                    stats.imported += 1
            job = session.get(ImportJob, job_id)
            if job is not None:
                job.discovered += len(batch.games)
                job.imported += stats.imported
                job.duplicates += stats.duplicates
                job.failed += stats.failed
                job.skipped += stats.skipped
                job.phase = f"Processed {batch.label}"
                if errors:
                    job.errors = (list(job.errors) + errors)[:MAX_ERRORS]
        return stats

    def _finish(self, job_id: str, *, error: str | None = None, cancelled: bool = False) -> None:
        with self.db.session() as session:
            job = session.get(ImportJob, job_id)
            if job is None:
                return
            job.finished_at = datetime.now(UTC)
            job.phase = None
            stored = f"{job.imported} new game{'s' if job.imported != 1 else ''}"
            if cancelled:
                job.status = CANCELLED
                job.message = f"Cancelled. {stored} were saved before stopping."
            elif error:
                job.status = PARTIAL if job.imported else FAILED
                job.message = error if not job.imported else f"{error} {stored} were saved before the error."
            elif job.failed:
                job.status = PARTIAL
                job.message = f"Imported {stored}; {job.failed} game(s) could not be read (see details)."
            else:
                job.status = COMPLETED
                parts = [f"Imported {stored}"]
                if job.duplicates:
                    parts.append(f"{job.duplicates} already in your library")
                if job.skipped:
                    parts.append(f"{job.skipped} skipped (unsupported)")
                if job.discovered == 0:
                    parts = ["No games matched your settings"]
                job.message = ", ".join(parts) + "."
        log.info("import finished", extra={"job": job_id})
