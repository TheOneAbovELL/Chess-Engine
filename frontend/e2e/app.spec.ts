import { expect, test, type Page } from "@playwright/test";

// A short game in which Black blunders into Scholar's mate (3...Nf6?? 4.Qxf7#).
const PGN = `[Event "E2E"]
[White "e2e-player"]
[Black "opponent"]
[Date "2026.10.01"]
[Result "1-0"]

1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0`;

async function stockfishAvailable(page: Page): Promise<boolean> {
  const engines = (await (await page.request.get("/api/v1/engines")).json()) as { id: string; available: boolean }[];
  return engines.some((e) => e.id === "stockfish" && e.available);
}

test("first visit shows the welcome state and navigation", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Welcome to ChessLab" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  await page.getByRole("link", { name: "Game History" }).click();
  await expect(page.getByText("Your library is empty")).toBeVisible();
});

test("analysis: typed move updates the board and the engine streams lines", async ({ page }) => {
  await page.goto("/analysis");
  await expect(page.getByRole("group", { name: "Analysis board" })).toBeVisible();
  await page.getByLabel("Type a move").fill("e4");
  await page.getByLabel("Type a move").press("Enter");
  await expect(page.getByRole("button", { name: /^1\.\s*e4$/ })).toBeVisible();
  // A line with an evaluation such as "+0.25" or "-0.10" appears.
  await expect(page.locator("li").filter({ hasText: /^[+-]?\d+\.\d\d/ }).first()).toBeVisible();
  await expect(page.getByText(/depth \d+/)).toBeVisible();
  // Illegal typed moves are rejected with a message.
  await page.getByLabel("Type a move").fill("Ke4");
  await page.getByLabel("Type a move").press("Enter");
  await expect(page.getByText(/is not a legal move here/)).toBeVisible();
});

test("PGN import, game history, review and dashboard", async ({ page }) => {
  await page.goto("/import");
  await page.getByLabel("PGN text").fill(PGN);
  await page.getByPlaceholder("e.g. MyHandle").fill("e2e-player");
  await page.getByRole("button", { name: "Import PGN" }).click();
  await expect(page.getByText(/1 imported/)).toBeVisible();

  await page.getByRole("link", { name: "Game History" }).click();
  await expect(page.getByText("e2e-player").first()).toBeVisible();
  await expect(page.getByText("Won")).toBeVisible();
  await page.getByRole("button", { name: "Open" }).first().click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("e2e-player");

  // Step through the game with the keyboard.
  await page.keyboard.press("End");
  await expect(page.getByText("7/7")).toBeVisible();

  test.skip(!(await stockfishAvailable(page)), "Stockfish is not installed; skipping the engine review step");
  await page.getByRole("button", { name: "Review this game" }).click();
  await expect(page.getByText(/Reviewed/)).toBeVisible({ timeout: 90_000 });
  // Jump to Black's 3...Nf6 (shown with its "??" blunder mark) and inspect it.
  await page.getByRole("button", { name: /^Nf6\s*\?\?$/ }).click();
  await expect(page.getByText("Blunder", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/Engine preferred/)).toBeVisible();

  await page.getByRole("link", { name: "Dashboard" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByText("1 game with your results", { exact: false })).toBeVisible();
});

test("play a move against the ChessLab engine", async ({ page }) => {
  await page.goto("/play");
  await page.getByRole("radio", { name: "ChessLab Engine" }).click();
  await page.getByRole("button", { name: "Start game" }).click();
  await page.locator("#play-board-square-e2").click();
  await page.locator("#play-board-square-e4").click();
  // The engine replies; the move list then shows two half-moves.
  await expect(page.locator("ol li").first()).toContainText(/1\.\s*e4\s*\S+/, { timeout: 60_000 });
  await page.getByRole("button", { name: "Resign" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Resign" }).click();
  await expect(page.getByText("You lost")).toBeVisible();
});

test("engine limits are enforced in the browser and on the server", async ({ page }) => {
  await page.goto("/settings");
  const threads = page.getByLabel("Stockfish threads");
  await threads.fill("999");
  await page.getByRole("button", { name: "Save engine settings" }).click();
  // The browser refuses the out-of-range value before sending anything...
  expect(await threads.evaluate((el) => (el as HTMLInputElement).validity.rangeOverflow)).toBe(true);
  // ...and the server rejects it independently if a client bypasses the form.
  const current = await (await page.request.get("/api/v1/settings/engine")).json();
  const response = await page.request.put("/api/v1/settings/engine", { data: { ...current, stockfish_threads: 999 } });
  expect(response.status()).toBe(422);
  expect((await response.json()).error.code).toBe("settings_out_of_range");
});
