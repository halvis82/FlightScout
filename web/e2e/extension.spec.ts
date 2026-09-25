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

// Round trip: the extension also hands over Google's full list (read in the
// visitor's own Google session), and the results mirror Google's two tabs.
test("with the extension, a round trip mirrors Google's Best and Cheapest tabs", async ({ baseURL }) => {
  const ext = path.resolve(__dirname, "../../extension");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "fs-ext-"));
  const ctx = await chromium.launchPersistentContext(dir, {
    channel: "chromium",
    headless: true,
    args: [`--disable-extensions-except=${ext}`, `--load-extension=${ext}`],
  });
  try {
    const page = await ctx.newPage();
    const bodies: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("/api/v1/browser")) bodies.push(r.postData() ?? "");
    });
    await page.goto(`${baseURL}/?from=LAX&to=DPS&d=2027-03-18&r=2027-03-29&smart=0`);
    await expect(page.getByText(/\d+ flights/)).toBeVisible({ timeout: 120_000 });
    await expect.poll(() => bodies.some((b) => b.includes('"list:https://www.google.com/travel/flights')), { timeout: 90_000 }).toBe(true);
    expect(Math.max(...bodies.map((b) => b.length))).toBeLessThan(4_000_000);
    await expect(page.getByRole("radio", { name: /Cheapest from/ })).toBeVisible();
    await page.getByRole("radio", { name: "Best" }).click();
    await expect(page.getByText("Top departing flights")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText("Other departing flights")).toBeVisible();
  } finally {
    await ctx.close();
  }
});
