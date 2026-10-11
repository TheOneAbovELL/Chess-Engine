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
from app.jobs import leases
from app.jobs.worker import BackgroundWorker, claim, requeue_stale, touch
from app.models import HttpCacheEntry, ImportJob
from app.models.jobs import ACTIVE_STATUSES, CANCELLED, COMPLETED, FAILED, PARTIAL, QUEUED, RUNNING
from app.repositories.games import GameRepository

from .chess.normalize import UnsupportedGameError, normalize_game
from .chess.openings import name_opening
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
    def __init__(self, service: GameImportService, job_id: str, user_id: int) -> None:
        self.service = service
        self.job_id = job_id
        self.user_id = user_id

    def _entry(self, session: Any, url: str) -> HttpCacheEntry | None:
        stmt = select(HttpCacheEntry).where(HttpCacheEntry.user_id == self.user_id, HttpCacheEntry.url == url)
        return session.execute(stmt).scalar_one_or_none()  # type: ignore[no-any-return]

    async def cache_validators(self, url: str) -> tuple[str | None, str | None]:
        def read() -> tuple[str | None, str | None]:
            with self.service.db.session() as session:
                entry = self._entry(session, url)
                return (entry.etag, entry.last_modified) if entry else (None, None)

        return await asyncio.to_thread(read)

    async def store_validators(self, url: str, etag: str | None, last_modified: str | None) -> None:
        if not etag and not last_modified:
            return

        def write() -> None:
            with self.service.db.session() as session:
                entry = self._entry(session, url)
                if entry is None:
                    session.add(HttpCacheEntry(user_id=self.user_id, url=url, etag=etag, last_modified=last_modified))
                else:
                    entry.etag, entry.last_modified = etag, last_modified

        await asyncio.to_thread(write)

    async def latest_played_at(self, source: str, owner: str) -> datetime | None:
        def read() -> datetime | None:
            with self.service.db.session() as session:
                return GameRepository(session, self.user_id).latest_played_at(source, owner)

        return await asyncio.to_thread(read)

    async def set_phase(self, phase: str) -> None:
        await asyncio.to_thread(self.service._update, self.job_id, phase=phase[:160])

    async def cancel_requested(self) -> bool:
        def read() -> bool:
            with self.service.db.session() as session:
                job = session.get(ImportJob, self.job_id)
                return bool(job and job.cancel_requested)

        return await asyncio.to_thread(read)


IMPORT_LEASE = "provider-imports"


class GameImportService(BackgroundWorker[str]):
    """Import jobs. One import talks to the providers at a time across every
    worker process (a database lease), which keeps ChessLab within the
    platforms' "one request at a time" guidance however it is deployed."""

    name = "import-worker"
    kind = "imports"
    poll_interval_s = 5.0

    def __init__(
        self, db: Database, settings: Settings, providers: dict[str, ChessHistoryProvider], store: SettingsStore
    ) -> None:
        super().__init__(db, settings.job_stale_after_s)
        self.settings = settings
        self.providers = providers
        self.store = store
        self._holding_lease = False

    # -------------------------------------------------------------- enqueue
    def create_job(self, user_id: int, params: ImportParams) -> dict[str, Any]:
        if params.max_games > self.settings.max_import_games:
            raise InvalidInputError(
                f"At most {self.settings.max_import_games} games per import.", code="too_many_games"
            )
        if params.provider not in self.providers:
            raise InvalidInputError(f"Unknown provider '{params.provider}'.", code="unknown_provider")
        with self.db.session() as session:
            active = (
                session.execute(
                    select(ImportJob).where(ImportJob.user_id == user_id, ImportJob.status.in_(ACTIVE_STATUSES))
                )
                .scalars()
                .all()
            )
            if any(j.provider == params.provider and j.username == params.username.lower() for j in active):
                raise ConflictError("An import for this account is already in progress.", code="import_in_progress")
            if len(active) >= self.settings.max_active_imports_per_user:
                raise ConflictError("You already have imports waiting. Let them finish first.", code="too_many_imports")
            job = ImportJob(
                id=str(uuid.uuid4()),
                user_id=user_id,
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

    @staticmethod
    def _owned(session: Any, user_id: int, job_id: str) -> ImportJob:
        job = session.get(ImportJob, job_id)
        if job is None or job.user_id != user_id:
            raise NotFoundError("Import job not found.")
        return job  # type: ignore[no-any-return]

    def get(self, user_id: int, job_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            return job_to_dict(self._owned(session, user_id, job_id))

    def list_jobs(self, user_id: int, limit: int = 20) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.execute(
                select(ImportJob).where(ImportJob.user_id == user_id).order_by(ImportJob.created_at.desc()).limit(limit)
            ).scalars()
            return [job_to_dict(j) for j in rows]

    def cancel(self, user_id: int, job_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            job = self._owned(session, user_id, job_id)
            if job.status == QUEUED:
                job.status, job.finished_at, job.message = CANCELLED, utcnow(), "Cancelled before it started."
            elif job.status == RUNNING:
                job.cancel_requested = True
            return job_to_dict(job)

    def retry(self, user_id: int, job_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            job = self._owned(session, user_id, job_id)
            if job.status in ACTIVE_STATUSES:
                raise ConflictError("This import is still running.", code="import_in_progress")
            params = ImportParams.model_validate(job.params)
        return self.create_job(user_id, params)

    # --------------------------------------------------------------- worker
    def requeue(self) -> None:
        requeue_stale(self.db, ImportJob, self.stale_after_s)

    def claim_next(self) -> str | None:
        with self.db.session() as session:
            self._holding_lease = leases.acquire(session, IMPORT_LEASE, self.worker_id, self.stale_after_s)
        if not self._holding_lease:
            return None  # another process is importing; wait our turn
        job_id = claim(self.db, ImportJob, ImportJob.created_at, self.worker_id)
        if job_id is None:
            self.after_job(None)
            return None
        self._update(str(job_id), phase="Starting")
        return str(job_id)

    def touch_job(self, job: str) -> None:
        touch(self.db, ImportJob, job, self.worker_id)

    def renew(self) -> None:
        if self._holding_lease and self.current is not None:
            with self.db.session() as session:
                leases.acquire(session, IMPORT_LEASE, self.worker_id, self.stale_after_s)

    def after_job(self, job: str | None) -> None:
        if self._holding_lease:
            with self.db.session() as session:
                leases.release(session, IMPORT_LEASE, self.worker_id)
            self._holding_lease = False

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
        user_id = job.user_id
        ctx = _JobContext(self, job_id, user_id)
        max_games = min(params.max_games, self.settings.max_import_games)
        log.info("import started", extra={"job": job_id, "provider": params.provider, "user": params.username})
        try:
            if params.provider == "chesscom":  # Lichess checks the account inside fetch()
                await ctx.set_phase("Checking the Chess.com account")
                await provider.lookup_user(params.username)
            async for batch in provider.fetch(params, ctx, max_games):
                batch.stats = await asyncio.to_thread(self._persist_batch, job_id, user_id, batch, params.username)
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
        await asyncio.to_thread(self.store.remember_account, user_id, params.provider, params.username)

    def _normalize(self, raw: RawGame, owner: str) -> Any:
        game = chess.pgn.read_game(io.StringIO(raw.pgn))
        if game is None:
            raise MalformedGameError("Empty PGN.")
        return normalize_game(
            game, owner=owner, source=raw.source, external_id=raw.external_id, overrides=raw.overrides
        )

    def _persist_batch(self, job_id: str, user_id: int, batch: ProviderBatch, owner: str) -> BatchStats:
        stats = BatchStats()
        errors: list[dict[str, str]] = []
        with self.db.session() as session:
            repo = GameRepository(session, user_id)
            limit = self.settings.max_games_per_user
            room = None if limit is None else max(0, limit - repo.count())
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
                if room is not None and stats.imported >= room:
                    stats.skipped += 1
                    errors.append({"ref": raw.ref, "error": "Your library is full (game limit reached)."})
                    continue
                name_opening(record)
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
