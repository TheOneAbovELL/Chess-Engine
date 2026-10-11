import { defineConfig, devices } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// End-to-end tests run the real stack: the production frontend build served by
// FastAPI, real engines, and a throwaway data directory (never your database).
//
//   npm run build && npm run e2e
//
// Browser: uses an installed Microsoft Edge (Windows) or Chrome via
// PLAYWRIGHT_CHANNEL, so no Playwright browser download is required.

const here = dirname(fileURLToPath(import.meta.url));
const PORT = 8765;
const backend = resolve(here, "../backend");
const python = process.platform === "win32" ? join(backend, ".venv", "Scripts", "python.exe") : join(backend, ".venv", "bin", "python");
const dataDir = mkdtempSync(join(tmpdir(), "chesslab-e2e-"));

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    channel: process.env.PLAYWRIGHT_CHANNEL ?? (process.platform === "win32" ? "msedge" : "chrome"),
    trace: "retain-on-failure",
    viewport: { width: 1366, height: 860 },
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Edge"], channel: process.env.PLAYWRIGHT_CHANNEL ?? (process.platform === "win32" ? "msedge" : "chrome") } },
  ],
  webServer: {
    command: `"${python}" -m uvicorn app.main:app --app-dir "${backend}" --host 127.0.0.1 --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/v1/health`,
    timeout: 120_000,
    reuseExistingServer: false,
    env: {
      CHESSLAB_DATA_DIR: dataDir,
      CHESSLAB_SERVE_FRONTEND: "true",
      CHESSLAB_FRONTEND_DIST: resolve(here, "dist"),
      CHESSLAB_CORS_ORIGINS: `["http://127.0.0.1:${PORT}"]`,
    },
  },
});
