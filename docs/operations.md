# Operations: data, backups, logs

## Data location

All personal data is one SQLite database plus its backups and logs in the **data directory**:

* Windows: `%LOCALAPPDATA%\ChessLab\` (e.g. `C:\Users\<you>\AppData\Local\ChessLab\`)
* Linux/macOS: `$XDG_DATA_HOME/chesslab` or `~/.local/share/chesslab`
* Docker: the `/data` volume
* Anywhere you like: `CHESSLAB_DATA_DIR` in `.env`

The directory is outside the repository on purpose: it is never committed and never synced by a cloud-synced project folder.

## Backups

The backup uses SQLite's online backup API, so it is consistent even while ChessLab is running.

* **In the app:** Settings → Your data → *Back up database now*.
* **From a terminal:**
  ```powershell
  backend\.venv\Scripts\python scripts\db_tool.py backup
  backend\.venv\Scripts\python scripts\db_tool.py list
  ```
* **Automatic:** before every schema migration (`pre-migration-*.db`) and before every restore (`pre-restore-*.db`).
* **Off-machine:** copy files from `<data dir>\backups\` to external storage yourself. ChessLab never uploads data.
* **Portable export:** *Export all games (PGN)* produces a standard PGN file usable by any chess software (reviews are not included in PGN).

## Restore

1. Stop ChessLab.
2. `backend\.venv\Scripts\python scripts\db_tool.py restore chesslab-<timestamp>.db`

The tool refuses to run while ChessLab is reachable on its port or while the database files are open (Windows), saves the current database as `pre-restore-<time>.db` first, removes stale WAL files and then restores. Start ChessLab again; migrations bring an older backup up to date automatically (backing it up first).

## Logs

* Console: human-readable `key=value` lines (or JSON with `CHESSLAB_LOG_JSON=true`).
* File: `<data dir>\logs\chesslab.log`, JSON lines, rotated at 5 MB, 3 files kept.
* Contents: startup/shutdown, migrations, engine start/stop/crash, import and review lifecycle, unhandled errors with stack traces. No game contents, no request bodies.

## Resetting

* Delete all games: Settings → Your data → *Delete all games* (type `DELETE` to confirm), or `DELETE /api/v1/data/games?confirm=DELETE`.
* Start completely fresh: stop ChessLab, back up, then delete (or rename) the data directory.

## Upgrades

See [deployment.md → Updating and rolling back](deployment.md#updating-and-rolling-back). Startup never deletes data. An unversioned database that already has tables is refused, not overwritten.
