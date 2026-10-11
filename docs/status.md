# Status, verification and next steps

Last updated: 2026-10-11 (initial build). Statuses reflect evidence, not intentions.

Legend: ✅ complete and verified · 🟡 implemented, partly verified · 🟠 partially implemented · ⛔ blocked by the environment · ❌ not implemented

## Verification environment

Windows 11, Python 3.13.3, Node 22.19.0, Stockfish 19 (official `stockfish-windows-x86-64-universal`, downloaded from the official GitHub release with the owner's approval), Microsoft Edge for browser tests. **No Docker.** Other CPU-heavy programs were running throughout, so timings are pessimistic. Nothing was pushed or uploaded; the Git repository has no remote.

## Automated checks (final run via `scripts\check.ps1 -E2E`)

| Check | Result |
| --- | --- |
| Backend ruff (lint + format) | ✅ clean (failed in the full run on 3 long lines in tests, fixed, rerun clean) |
| Backend mypy `--strict` (57 files) | ✅ no issues |
| Backend pytest (mocked HTTP; real custom engine; real Stockfish 19) | ✅ 149 passed, 3 deselected (live tests run separately); Stockfish tests ran (not skipped) |
| Engine ruff + pytest | ✅ ruff clean; 46 passed |
| Frontend `tsc -b` (strict) | ✅ no errors |
| Frontend ESLint (incl. React Hooks v7 rules) | ✅ no problems |
| Frontend Vitest | ✅ 21 passed (3 files) |
| Frontend production build | ✅ built (code-split per page) |
| Playwright E2E in Edge against the real stack | ✅ 5 passed (Edge; includes a real Stockfish game review) |
| Live provider tests (`pytest -m live`, real Chess.com + Lichess) | 3 passed (run separately during development) |

## Definition of done

### Core functionality

| Item | Status | Evidence |
| --- | --- | --- |
| Board validates legal moves; drag, click-to-move, promotion picker, typed moves | ✅ | Frontend unit tests, E2E (typed + clicked moves), manual browser session; illegal drops snap back |
| Standard rules and endings (mate, stalemate, repetition, 50/75-move, insufficient material) | ✅ | `test_chess_rules.py`, `eval.test.ts` (`gameStatus`) |
| Stockfish returns real analysis | ✅ | `test_engines.py` (Stockfish tests), WebSocket test, browser session (3 lines at depth 22) |
| Depth and time limits | ✅ | Engine tests (time cap honoured), API tests (limits rejected above ceilings) |
| Candidate lines and evaluations display correctly | ✅ | Browser session; a mixed-depth MultiPV bug was found there and fixed (completed iterations only, unit-tested) |
| Analysis can be stopped safely | ✅ | Stop/preemption tests (engine and WebSocket), crash-recovery tests |
| Chess.com public history import | ✅ | 19 mocked job tests, live test (`erik`), browser import of 25 games (18 imported, 7 variants skipped) |
| Lichess public history import | ✅ | 7 mocked job tests (streaming split across chunks, `since`, 429/60 s), live test (`thibault`); the browser UI is the same for both providers |
| Imported games persist across restarts | ✅ | `test_games_persist_across_restarts`; browser data survived backend restarts |
| Duplicate imports prevented | ✅ | Re-import, refresh, interrupted-resume and PGN-vs-API dedupe tests |
| Games can be replayed | ✅ | Review page (keyboard, move list, graph); E2E |
| Game analysis produces position-specific results | ✅ | `test_reviews.py` (real engines), E2E (Stockfish review flags 3...Nf6?? as a blunder), browser review of a 106-ply game |
| Dashboard uses actual stored data | ✅ | `test_statistics.py` on known datasets; browser dashboard from 18 real games |
| Custom engine works independently | ✅ | 46 engine tests incl. UCI subprocess; bench signature reproducible (88,551 nodes at depth 4) |
| Engine comparison interface | ✅ | Browser: Stockfish d4 (+0.23) vs ChessLab e4 (+0.13) at depth 6 |

### Engineering quality

| Item | Status | Evidence |
| --- | --- | --- |
| Automated tests pass | ✅ | See table above |
| Frontend type check and lint | ✅ | `tsc -b`, ESLint |
| Production build | ✅ | `vite build`; served by FastAPI in E2E |
| API validation and error handling | ✅ | Pydantic schemas, uniform error envelope, tests for 404/409/413/422/429/503 |
| Engine resource limits | ✅ | ≤ 3 engine processes by design; depth/time/MultiPV/threads/hash ceilings; rate limit; tests |
| Migrations and persistence | ✅ | Alembic; pre-migration backup and unversioned-DB refusal tested |
| No secrets in the repository | ✅ | Secret-pattern scan of tracked files; `.env` ignored; `.env.example` has no values |
| Configuration documented | ✅ | `.env.example`, [setup.md](setup.md) |
| Third-party licences addressed | ✅ | [third-party-licenses.md](third-party-licenses.md) (incl. python-chess GPL implications) |

### User experience

| Item | Status | Evidence / gap |
| --- | --- | --- |
| Visually polished | 🟡 | Reviewed in the browser at 1280 px and 375 px; no external design review |
| Responsive core interactions | 🟡 | Analysis verified on mobile (a layout bug was found and fixed); other pages use the same responsive patterns but were only checked at desktop width |
| Loading, empty and error states | ✅ | Seen in the browser (server offline, skeletons, empty library, no-match filters, failed/partial imports) and in component tests |
| Keyboard and accessibility | 🟡 | Keyboard navigation (← → Home End F), typed-move input, labelled form fields (an association bug was caught by E2E and fixed), dialogs, a screen-reader description of the position, reduced-motion support. **Not** audited with a screen reader; the board library renders pieces as unlabelled buttons (the position description compensates) |
| No dead controls | ✅ | Every button is wired to a working action; nothing is presented as a feature that does not exist |

### Delivery

| Item | Status | Evidence / gap |
| --- | --- | --- |
| README with working setup | ✅ | `scripts\setup.ps1` run end to end on this machine |
| Clean-setup start | 🟡 | Setup verified from an existing checkout; a brand-new clone on another PC was not tested |
| Stockfish installation documented | ✅ | `install_stockfish.ps1 -DryRun` selects the same official asset that was installed manually |
| Testing documented | ✅ | [development.md](development.md) |
| Deployment constraints documented | ✅ | [deployment.md](deployment.md) |
| Docker image | ⛔ | Dockerfile + compose provided; **not built** (Docker not installed) |
| CI workflow | 🟡 | `.github/workflows/ci.yml` provided; **never executed** (the repository was deliberately not pushed) |
| Git hygiene | ✅ | Local commits only, no remote; data, engines, `.env`, `node_modules`, builds ignored |

## Defects found and fixed during verification

* Windows `uvicorn --reload` cannot start engine subprocesses (SelectorEventLoop). Fixed by the dedicated Proactor engine thread.
* Engines at below-normal priority were starved by other CPU-heavy programs. Low priority is now opt-in.
* Lichess returns a misleading 404 without an identifying User-Agent. ChessLab always identifies itself.
* MultiPV lines from different depths were mixed. Snapshots now contain completed iterations only.
* Eval bar took the full width on phones (Tailwind class conflict). Fixed.
* WebSocket hook lost its socket under React StrictMode remounts. Fixed.
* Chess.com opening names kept a trailing move number. Fixed, with a regression test.
* SQLite connections in backups were not closed (`with sqlite3.connect()` only commits). Fixed.
* Form labels were not associated with inputs. Fixed.
* `npm ci` in setup could leave `node_modules` half-deleted when files were locked. Setup now refuses to run while ChessLab is running and updates in place.
* Shared TLS context cut HTTP-client start-up from 1.65 s to 0.39 s.

## Known limitations

* Single-user, unauthenticated; do not expose publicly without adding authentication.
* Standard chess only; variants are skipped on import.
* PGNs without opening metadata show no opening name (no ECO database bundled).
* Opening names for games imported *before* the slug fix keep their trailing number until re-imported (only relevant to the development database).
* The custom engine is weak and slow by design (pure Python, ~5–20k nodes/s); no Elo claim.
* Classification thresholds are heuristics; see [game-review.md](game-review.md).
* Lichess's "Normal" termination cannot distinguish mate from resignation in the "how games end" chart.
* Node 22.19 triggers an engine warning for a test-only dependency (jsdom); use Node 22.22+ or 24 LTS to silence it.
* The project folder lives in OneDrive on the development machine; `node_modules` and `.venv` are synced by OneDrive unless excluded.

## Recommended next steps

1. Build and run the Docker image once Docker Desktop is available (`docker compose up --build`), then tick the Docker item.
2. If you publish the repository, watch the first CI run and fix any Linux-specific differences (CI uses Debian's older Stockfish).
3. Screen-reader pass (NVDA) over Analysis, Review and Import; consider a custom board renderer with labelled squares.
4. Add an ECO/opening-name dataset (e.g. lichess-org/chess-openings, CC0) so plain PGNs and the explorer show opening names.
5. Engine: incremental Zobrist/evaluation, SEE, aspiration windows; then measure with `match.py` over ≥ 200 games.
6. Puzzles from your own blunders (positions and best moves are already stored by reviews).
7. Optional authentication layer before any hosted deployment.
