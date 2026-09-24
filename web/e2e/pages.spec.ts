import { expect, test } from "@playwright/test";
import { watchErrors } from "./helpers";

test("airlines directory prefills routes and opens in a new tab", async ({ page }) => {
  await page.goto("/airlines");
  await expect(page.getByText(/\d+ airlines/)).toBeVisible();
  const input = page.getByPlaceholder("From (optional)");
  await input.click();
  await input.fill("OSL");
  await page.getByRole("option").first().click();
  const to = page.getByPlaceholder("To (optional)");
  await to.click();
  await to.fill("CPH");
  await page.getByRole("option").first().click();
  const sas = page.getByRole("link", { name: /Search OSL to CPH/ }).first();
  await expect(sas).toHaveAttribute("target", "_blank");
  await expect(sas).toHaveAttribute("href", /OSL/);
});

test("watchlist panel, settings and history open without errors", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/");
  await page.getByRole("button", { name: /Watchlist/ }).first().click();
  await expect(page.getByText("Checked twice a day")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.goto("/settings");
  await expect(page.getByText("Start searches from")).toBeVisible();
  await expect(page.getByText("Favorite airports and cities")).toBeVisible();
  await page.goto("/history");
  expect(errors).toEqual([]);
});

test("watch is one click for guests", async ({ page }) => {
  await page.goto("/?from=OSL&to=CPH&tt=oneway&d=2026-11-19");
  await expect(page.getByText(/\d+ flights/)).toBeVisible();
  await page.getByRole("button", { name: "Watch this search" }).click();
  await expect(page.getByText(/Watching OSL to CPH/)).toBeVisible();
});

test("signups are invite only", async ({ request, baseURL }) => {
  const r = await request.post("/api/auth/sign-up/email", {
    headers: { origin: baseURL! },
    data: { email: `stranger-${Date.now()}@example.com`, password: "Sup3rsecret!!x", name: "x" },
  });
  expect(r.status()).toBeGreaterThanOrEqual(400);
  expect(await r.text()).toMatch(/invite only/);
});
