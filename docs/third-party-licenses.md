# Third-party software and licences

ChessLab's own source code is licensed under the MIT License (see `LICENSE`). That licence covers **only** ChessLab's own code. Every component below keeps its own licence, and nothing in ChessLab's licence overrides them.

## Components with copyleft obligations

| Component | Licence | How ChessLab uses it | What it means |
| --- | --- | --- | --- |
| **Stockfish** | GPL-3.0 | Separate executable, started as a subprocess and driven over UCI. Not bundled in the repository (downloaded by `scripts/install_stockfish.ps1` or installed by the Docker image from Debian). | If you **distribute** Stockfish (e.g. in a Docker image or an installer), you must provide its licence and the corresponding source code (the official ZIPs contain both). Running it locally carries no obligations. |
| **python-chess** (`chess`) | GPL-3.0-or-later | Imported by the backend and by the ChessLab engine. | ChessLab's own files may stay MIT (MIT is GPL-compatible), but if you **distribute** the backend or engine together with python-chess, the combined program must be distributed under GPL-3.0 terms (source available, GPL notice preserved). Using it privately has no such requirement. |

If you prefer one licence for everything, licensing the whole repository under GPL-3.0-or-later is a simple, compatible alternative; that is the project owner's choice.

## Python runtime dependencies

| Package | Licence |
| --- | --- |
| FastAPI | MIT |
| Starlette | BSD-3-Clause |
| Uvicorn | BSD-3-Clause |
| Pydantic, pydantic-settings | MIT |
| SQLAlchemy, Alembic | MIT |
| httpx | BSD-3-Clause |
| certifi | MPL-2.0 (CA bundle; unmodified) |

Development tools (not shipped): pytest (MIT), pytest-asyncio (Apache-2.0), pytest-timeout (MIT), respx (BSD-3-Clause), ruff (MIT), mypy (MIT).

## Frontend dependencies (bundled into the built JavaScript/CSS)

| Package | Licence |
| --- | --- |
| React, React DOM | MIT |
| React Router | MIT |
| TanStack Query | MIT |
| Zustand | MIT |
| chess.js | BSD-2-Clause |
| react-chessboard (including its piece images) and @dnd-kit | MIT |
| Recharts | MIT |
| lucide-react (icons) | ISC |
| Tailwind CSS | MIT |
| Inter, JetBrains Mono (via @fontsource-variable) | SIL Open Font License 1.1 |

Development tools (not shipped): Vite, Vitest, ESLint, typescript-eslint, Testing Library, jsdom (MIT); TypeScript, Playwright (Apache-2.0).

The production build is created by Vite; licence comments of bundled packages are preserved where the packages include them. To produce a full notice file for a distribution, run a licence collector such as `npx license-checker --production` in `frontend/`.

## Data and other material

* **PeSTO piece-square tables:** values by Ronald Friederich, as published on the Chess Programming Wiki (content there is licensed CC BY-SA 3.0). They are attributed in `engine-lab/chesslab_engine/pst.py`. If you redistribute the engine, keep that attribution.
* **Game data** imported from Chess.com or Lichess belongs to the respective players/platforms and is retrieved through their public APIs for personal analysis. Respect each platform's terms of service.
* **Opening names** come from the games' own metadata (Lichess `Opening` headers, Chess.com ECO URLs). No opening database is bundled.
