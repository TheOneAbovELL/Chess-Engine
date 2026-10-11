# API reference

Base path: `/api/v1`. Interactive OpenAPI documentation is served by the backend at **`/api/docs`** (Swagger UI) and the schema at `/api/openapi.json`.

## Conventions

* JSON in and out; request bodies are validated by Pydantic (types, ranges, lengths, UCI move patterns).
* **Errors** always use one envelope, never internal exception text:
  ```json
  { "error": { "code": "illegal_move", "message": "Illegal move 'e2e5' at ply 1.", "details": null } }
  ```
  Common codes: `validation_error` (422), `invalid_fen`, `illegal_position`, `illegal_move`, `invalid_pgn`, `limit_too_high`, `not_found` (404), `conflict`/`import_in_progress` (409), `payload_too_large` (413), `rate_limited` (429), `engine_unavailable` (503), `provider_*` (Chess.com/Lichess failures), `internal_error` (500).
* **Scores** are always from **White's point of view**: `{"cp": 34, "mate": null}`; `mate > 0` White mates, `mate < 0` Black mates, `mate == 0` the side to move is checkmated.
* **Positions** are sent as `fen` (optional, default start position) plus `moves` (UCI list). Sending the move history lets engines see repetitions.
* Large collections are paginated (`page`, `page_size` ≤ 100) and return `{items, total, page, page_size}`.
* Long work (imports, reviews) is asynchronous: the POST returns `202` with a job, which you poll.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness, database and engine status |
| `GET` | `/config` | Limits and providers the UI should respect (no filesystem paths) |
| `GET` | `/engines` | Engines, availability, status and capabilities |
| `GET` | `/engines/levels` | Play-strength levels per engine |
| `POST` | `/engines/{engine_id}/stop` | Stop the engine's current interactive search |
| `GET` | `/engines/custom/evaluate?fen=` | Static evaluation breakdown of the ChessLab engine |
| `GET` / `PUT` | `/settings/engine` | Engine resources and defaults (validated against server ceilings) |
| `GET` / `PUT` | `/settings/classification` | Move-classification thresholds |
| `GET` / `PUT` | `/settings/preferences` | Linked accounts |
| `POST` | `/positions/validate` | Validate a position; status (check, mate, draws) and legal moves |
| `POST` | `/pgn/parse` | Parse the first game of a PGN into a move tree (with variations) |
| `POST` | `/pgn/validate` | Count valid/invalid games in a PGN without storing it |
| `POST` | `/analysis` | One bounded analysis (default depth 18, capped by time) |
| `POST` | `/analysis/best-move` | Engine move for play mode (`level` or `depth`/`movetime_ms`) |
| `POST` | `/analysis/compare` | Run several engines on the same position, one after another |
| `WS` | `/analysis/live` | Live analysis stream (see below) |
| `GET` | `/games` | List games: `q, source, owner, color, result, time_class, rated, date_from, date_to, opening, min_rating, max_rating, reviewed, sort, page, page_size` |
| `GET` | `/games/owners` | Imported accounts and game counts |
| `GET` | `/games/export.pgn` | Export the filtered games as one PGN file |
| `POST` | `/games/import-pgn` | Import PGN text (multi-game; duplicates skipped; per-game errors) |
| `POST` | `/games/save` | Save a game played in ChessLab |
| `POST` | `/games/delete` | Delete several games |
| `GET` / `DELETE` | `/games/{id}` | One game with moves/headers, or delete it (reviews cascade) |
| `GET` | `/games/{id}/pgn` | Download one game |
| `POST` / `GET` | `/games/{id}/review` | Queue a review / latest review with per-position results |
| `POST` | `/reviews/batch` | Queue reviews for several games |
| `GET` | `/reviews/queue` | Queued and running reviews |
| `GET` | `/reviews/{id}?positions=true` | Review status, optionally with positions |
| `POST` | `/reviews/{id}/cancel` · `/retry` · `/reclassify` | Control a review; reclassify uses current thresholds without re-analysis |
| `GET` | `/providers` | Supported providers and their notes |
| `GET` | `/providers/{provider}/users/{username}` | Check a public account |
| `GET` | `/providers/{provider}/users/{username}/preview` | A few recent games, not imported |
| `POST` | `/imports` | Start an import job (`provider, username, mode, max_games, since, until, time_classes, color, rated`) |
| `GET` | `/imports` · `/imports/{id}` | Recent jobs / one job with counters and errors |
| `POST` | `/imports/{id}/cancel` · `/retry` | Cancel / re-run an import |
| `POST` | `/imports/refresh-all` | Start "new games only" imports for all linked accounts |
| `GET` | `/stats/summary` | Dashboard statistics (same filters as `/games`) |
| `GET` | `/explorer?moves=e2e4&moves=e7e5` | Personal opening tree at a position |
| `GET` | `/data/info` | Counts, database size, backups |
| `POST` | `/data/backup` | Consistent copy of the database into the backups folder |
| `DELETE` | `/data/games?confirm=DELETE` | Delete every stored game |

## Live analysis WebSocket

`ws://127.0.0.1:8000/api/v1/analysis/live` (through the Vite dev proxy in development).

Client → server:

```json
{"type": "start", "request_id": "r7", "fen": null, "moves": ["e2e4", "e7e5"], "engine": "stockfish", "multipv": 3, "depth": null, "movetime_ms": null}
{"type": "stop"}
```

Server → client (each carries the `request_id` it belongs to; ignore stale ids):

```json
{"type": "update", "request_id": "r7", "snapshot": {"depth": 17, "lines": [...], "nodes": 1840000, ...}}
{"type": "done",   "request_id": "r7", "snapshot": {..., "final": true, "stop_reason": "stopped"}}
{"type": "error",  "request_id": "r7", "code": "invalid_fen", "message": "..."}
```

Snapshots only contain **completed** iterations (all MultiPV lines at the same depth). Starting a new analysis stops the previous one. Without a depth/time limit an analysis stops automatically after `CHESSLAB_MAX_LIVE_ANALYSIS_SECONDS` (default 180 s). Browsers' `Origin` must be an allowed origin or the same host (cross-site WebSocket hijacking protection). At most four live connections are accepted.

## Resource limits

All engine work is bounded: depth ≤ `MAX_SEARCH_DEPTH`, time ≤ `MAX_ANALYSIS_SECONDS` (one-shot) / `MAX_LIVE_ANALYSIS_SECONDS` (live), MultiPV ≤ `MAX_MULTIPV`, threads and hash ≤ server ceilings, analysis requests ≤ `ANALYSIS_RATE_PER_MINUTE` per client, request bodies ≤ `MAX_REQUEST_BYTES` (6 MB), PGN ≤ `MAX_PGN_BYTES` (5 MB) and ≤ 2000 games per upload, imports ≤ `MAX_IMPORT_GAMES`. At most three engine processes ever run (interactive Stockfish, interactive custom engine, one review engine).
