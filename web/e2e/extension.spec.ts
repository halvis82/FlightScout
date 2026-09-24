import { chromium, expect, test } from "@playwright/test";
import path from "node:path";
import os from "node:os";
import fs from "node:fs";

// Loads the real FlightScout Helper extension and checks that Google searches
// go through the visitor's browser (/api/v1/browser rounds) and finish.
test("with the extension, Google searches run from the browser", async ({ baseURL }) => {
  const ext = path.resolve(__dirname, "../../extension");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "fs-ext-"));
  const ctx = await chromium.launchPersistentContext(dir, {
    channel: "chromium",
    headless: true,
    args: [`--disable-extensions-except=${ext}`, `--load-extension=${ext}`],
  });
  try {
    const page = await ctx.newPage();
    const rounds: number[] = [];
    page.on("requestfinished", (r) => {
      if (r.url().includes("/api/v1/browser")) rounds.push((r.postData() ?? "").length);
    });
    await page.goto(`${baseURL}/?from=OSL&to=CPH&tt=oneway&d=2026-11-19&smart=0`);
    await expect(page.getByText("Your IP")).toBeVisible();
    await expect(page.getByText(/\d+ flights/)).toBeVisible({ timeout: 90_000 });
    await expect.poll(() => rounds.length, { timeout: 60_000 }).toBeGreaterThanOrEqual(2); // ask, then pages
    expect(Math.max(...rounds)).toBeLessThan(4_000_000); // under Vercel's request limit
  } finally {
    await ctx.close();
  }
});
