"""Download my data: everything ChessLab stores for one user, as a zip."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.core.config import APP_VERSION
from app.db.session import Database
from app.models import Game, GameReview, ImportJob
from app.repositories.games import GameFilters
from app.services.auth import CurrentUser
from app.services.games import GameService
from app.services.review.service import review_to_dict
from app.services.settings_store import SettingsStore

README = """ChessLab data export
====================

games.pgn      every stored game (standard PGN; opens in any chess program)
reviews.json   completed engine reviews with per-move evaluations
settings.json  your ChessLab settings and linked public accounts
account.json   account details

Passwords are never exported (only a one-way hash is stored on the server).
"""


def counts(db: Database, user_id: int) -> dict[str, int]:
    with db.session() as session:
        return {
            "games": session.execute(select(func.count(Game.id)).where(Game.user_id == user_id)).scalar_one(),
            "completed_reviews": session.execute(
                select(func.count(GameReview.id)).where(GameReview.user_id == user_id, GameReview.status == "completed")
            ).scalar_one(),
            "import_jobs": session.execute(
                select(func.count(ImportJob.id)).where(ImportJob.user_id == user_id)
            ).scalar_one(),
        }


def export_archive(db: Database, games: GameService, store: SettingsStore, user: CurrentUser) -> bytes:
    with db.session() as session:
        reviews = [
            review_to_dict(r, with_positions=True)
            for r in session.execute(
                select(GameReview)
                .where(GameReview.user_id == user.id, GameReview.status == "completed")
                .order_by(GameReview.id)
            ).scalars()
        ]
    account: dict[str, Any] = {
        "username": user.username,
        "display_name": user.display_name,
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "chesslab_version": APP_VERSION,
        **counts(db, user.id),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", README)
        archive.writestr("games.pgn", games.export(user.id, GameFilters(), limit=1_000_000))
        archive.writestr("reviews.json", json.dumps(reviews, default=str, indent=1))
        archive.writestr("settings.json", json.dumps(store.export(user.id), indent=2))
        archive.writestr("account.json", json.dumps(account, indent=2))
    return buffer.getvalue()
