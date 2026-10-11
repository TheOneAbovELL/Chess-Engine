"""Back up or restore the local ChessLab database.

Usage (from the repository root, with the backend virtualenv's Python):

    backend\\.venv\\Scripts\\python scripts\\db_tool.py backup
    backend\\.venv\\Scripts\\python scripts\\db_tool.py list
    backend\\.venv\\Scripts\\python scripts\\db_tool.py restore chesslab-20261011T120000Z.db

* ``backup`` makes a consistent copy with SQLite's online backup API, so it is
  safe even while ChessLab is running.
* ``restore`` must run while ChessLab is stopped. It first saves the current
  database as ``pre-restore-<timestamp>.db``, so a restore can be undone.
"""

from __future__ import annotations

import argparse
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings  # noqa: E402
from app.db.migrate import backup_sqlite, sqlite_path  # noqa: E402


def file_in_use(path: Path) -> bool:
    """On Windows a file another process holds open (as SQLite does) cannot be
    renamed. Elsewhere this returns False and the port check has to suffice."""
    if not path.exists():
        return False
    probe = path.with_name(path.name + ".probe")
    try:
        path.rename(probe)
    except PermissionError:
        return True
    probe.rename(path)
    return False


def server_running(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("backup")
    sub.add_parser("list")
    restore = sub.add_parser("restore")
    restore.add_argument("name", help="backup file name (from 'list') or a path")
    args = parser.parse_args()

    settings = Settings()
    db_path = sqlite_path(settings.resolved_database_url)
    if db_path is None:
        print("Only the default SQLite database can be managed with this tool.")
        return 1
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    if args.command == "list":
        backups = sorted(settings.backups_dir.glob("*.db"), reverse=True)
        print(f"Database: {db_path}")
        print(f"Backups in {settings.backups_dir}:" if backups else "No backups yet.")
        for b in backups:
            print(f"  {b.name}  ({b.stat().st_size / 1024:.0f} KB)")
        return 0

    if args.command == "backup":
        if not db_path.exists():
            print(f"No database at {db_path} yet.")
            return 1
        target = backup_sqlite(db_path, settings.backups_dir / f"chesslab-{stamp}.db")
        print(f"Backup written to {target}")
        return 0

    source = Path(args.name)
    if not source.is_absolute():
        source = settings.backups_dir / args.name
    if not source.is_file():
        print(f"Backup not found: {source}")
        return 1
    if server_running(settings.host, settings.port):
        print(f"ChessLab appears to be running on {settings.host}:{settings.port}. Stop it before restoring.")
        return 1
    if any(file_in_use(db_path.with_name(db_path.name + suffix)) for suffix in ("", "-wal", "-shm")):
        print("The database is open in another program (is ChessLab still running?). Stop it before restoring.")
        return 1
    if db_path.exists():
        safety = backup_sqlite(db_path, settings.backups_dir / f"pre-restore-{stamp}.db")
        print(f"Current database saved as {safety.name}")
    for suffix in ("-wal", "-shm"):  # stale WAL files must not be replayed onto the restored file
        stale = db_path.with_name(db_path.name + suffix)
        if stale.exists():
            stale.unlink()
    backup_sqlite(source, db_path)
    print(f"Restored {source.name} -> {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
