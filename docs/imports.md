# Importing games from Chess.com and Lichess

ChessLab reads **public** game history through each platform's **official, free** API. No password, token, API key, paid plan or scraping is involved. Imported games are stored only in your local database.

## Chess.com: Published-Data API

Docs: <https://www.chess.com/news/view/published-data-api>

| Step | Request |
| --- | --- |
| Check the account | `GET https://api.chess.com/pub/player/{username}` (404 = no such public player) |
| List monthly archives | `GET https://api.chess.com/pub/player/{username}/games/archives` |
| Read a month | `GET https://api.chess.com/pub/player/{username}/games/{YYYY}/{MM}` (JSON; each game has its PGN, `time_class`, `rules`, `end_time`, ratings) |

* Months are read **newest first** and **one request at a time** (Chess.com only rate-limits parallel requests).
* Games are identified by their URL (`live/<id>` or `daily/<id>`), which is also recognised in uploaded PGNs, so the same game never appears twice.
* Variants (`rules` other than `chess`, e.g. Chess960) are skipped and reported as *skipped*.
* **Refresh ("only new games")** sends `If-None-Match` / `If-Modified-Since` validators saved after a month was **completely** imported. An unchanged month answers `304 Not Modified` (no download, no parsing) and the refresh stops there. Validators are not saved for filtered or truncated imports, and they are cleared whenever you delete games, so deleted games come back on the next refresh.
* Chess.com documents that its data may be cached for up to 12–24 hours, so a game you just finished may not appear immediately.

## Lichess: games export

Docs: <https://lichess.org/api#tag/Games/operation/apiGamesUser>

| Step | Request |
| --- | --- |
| Check the account | `GET https://lichess.org/api/user/{username}` (404 = unknown; `disabled` = closed) |
| Export games | `GET https://lichess.org/api/games/user/{username}` with `Accept: application/x-chess-pgn` |

* Parameters used: `max`, `since`, `until`, `perfType`, `color`, `rated`, `clocks=true`, `opening=true`, `sort=dateDesc`.
* The response is **streamed** and parsed game by game, so progress updates while it downloads. Anonymous clients receive about 20 games per second.
* **Refresh** asks only for games after the newest stored Lichess game (`since`), so no history is downloaded twice.
* **Lichess requires an identifying `User-Agent`.** Without one the export endpoint answers with a generic 404 page (see lichess-org/api issue #667). ChessLab always sends `ChessLab/<version> (local-first personal chess analysis app)`; set `CHESSLAB_HTTP_CONTACT` to append contact details, as both platforms recommend.

## Reliability

| Situation | Behaviour |
| --- | --- |
| Invalid username format | Rejected before any request (2–30 letters, digits, `_`, `-`). |
| Unknown user / closed account | Import fails with a clear message; nothing stored. |
| Empty history / no matching games | Completed with "No games matched your settings". |
| Network error or timeout | Up to 3 retries with exponential backoff (1 s, 3 s, 9 s), then a clear failure. |
| HTTP 429 (rate limited) | Waits `Retry-After` or the platform's guidance (Chess.com 10 s, Lichess 60 s), retries up to 3 times. |
| HTTP 5xx | Retried with backoff, then reported. |
| Unexpected response format | Reported as an unexpected format; nothing half-parsed is stored. |
| Malformed PGN for one game | That game is counted as *failed* with its reason; others continue (status *partial*). |
| Unsupported variant | Counted as *skipped* with its reason. |
| Duplicates | Counted as *already had*; never stored twice. |
| App closed mid-import | Already-stored batches are kept; the job is re-queued on next start and completes without duplicates. |
| Cancel | Stops after the current batch; stored games are kept. |

Job outcomes are honest: **completed** only if every discovered game was stored, recognised as a duplicate or skipped for a stated reason; **partial** if some games failed or the provider failed after some were stored; **failed** if nothing could be imported.

## What cannot be imported

Private, deleted, hidden or restricted games; games of closed accounts (Lichess); games still in progress; variants. Public-data access does not guarantee that every historical game is available.

## Costs and licensing

* **API access:** free; both APIs are rate-limited and best-effort.
* **Computing:** analysis runs on your own CPU (Stockfish); no cloud analysis and no AI provider.
* **Hosting:** none needed locally. If you host ChessLab yourself, that hosting may cost money.
* **Licensing:** game data belongs to the respective players/platforms; use it for personal analysis.
