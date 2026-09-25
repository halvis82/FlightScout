import { expect, test } from "@playwright/test";
import { clearFrom, fresh, pickAirport, watchErrors } from "./helpers";

test.describe("search", () => {
  test("picking From and To searches by itself (no Search click) and streams results", async ({ page }) => {
    const errors = watchErrors(page);
    await fresh(page);
    await clearFrom(page);
    await pickAirport(page, /Where from|Add airport/, "lax", "LAX");
    await pickAirport(page, "Anywhere (explore)", "denpasar", "Denpasar");
    // step count: two picks, zero clicks on Search
    await expect(page.getByText(/\d+ flights/)).toBeVisible({ timeout: 60_000 });
    const logos = await page.locator("img[alt]").evaluateAll((els) => new Set(els.map((e) => (e as HTMLImageElement).alt)).size);
    expect(logos, "several airlines in results").toBeGreaterThan(3);
    expect(errors).toEqual([]);
  });

  test("date arrow re-searches and keeps old results visible meanwhile", async ({ page }) => {
    await page.goto("/?from=OSL&to=CPH&tt=oneway&d=2026-11-19");
    await expect(page.getByText(/\d+ flights/)).toBeVisible();
    const before = await page.locator("form").innerText();
    await page.locator("form button[aria-label*='later'], form button[aria-label*='Next']").first().click();
    await expect(page.getByText(/\d+ flights/)).toBeVisible(); // never blank
    expect(await page.locator("form").innerText()).not.toEqual(before);
  });

  test("trip presets and flexibility are one click", async ({ page }) => {
    await fresh(page);
    await page.getByRole("button", { name: "Weekend" }).click();
    const ret = page.locator("form").getByText("Return", { exact: true });
    await expect(ret.first()).toBeVisible();
    await page.getByRole("button", { name: "One flight" }).click();
    await expect(ret).toHaveCount(0);
    await page.getByRole("radio", { name: "Round trip" }).click();
    await page.getByRole("button", { name: "±2" }).first().click();
  });

  test("clicking an airport in the dropdown adds it", async ({ page }) => {
    await fresh(page);
    await clearFrom(page);
    await pickAirport(page, /Where from|Add airport/, "san diego", "San Diego");
    await expect(page.locator("form")).toContainText("SAN");
  });

  test("logo resets and tabs keep the search", async ({ page }) => {
    await page.goto("/?from=OSL&to=CPH&tt=oneway&d=2026-11-19");
    await expect(page.getByText(/\d+ flights/)).toBeVisible();
    await page.getByRole("link", { name: "Airlines" }).click();
    await page.getByRole("link", { name: "Search", exact: true }).first().click();
    await expect(page.locator("form")).toContainText("CPH");
    await page.getByRole("link", { name: "FlightScout" }).first().click();
    await expect(page.locator("form")).not.toContainText("CPH");
  });

  test("multi-city searches in order", async ({ page }) => {
    const legs = [
      { to: ["JFK"], date: "2026-11-03", flex: 1 },
      { to: ["SAN"], date: "2026-11-10", flex: 1 },
    ];
    await page.goto(`/?from=SAN&tt=multicity&d=2026-11-03&ml=${encodeURIComponent(JSON.stringify(legs))}`);
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await expect(page.getByText(/\$[\d,]+/).first()).toBeVisible({ timeout: 90_000 });
    await expect(page.getByText("SAN → JFK → SAN")).toBeVisible();
  });
});

test("switching currency converts every price on screen", async ({ page }) => {
  await page.goto("/?from=OSL&to=CPH&tt=oneway&d=2026-11-19");
  await expect(page.getByText(/\d+ flights/)).toBeVisible();
  await page.getByRole("button", { name: /^Currency:/ }).first().click();
  await page.getByRole("menuitemradio", { name: /NOK/ }).first().click();
  await expect(page.locator("main").getByText(/NOK\s?[\d,]+|kr\s?[\d,]+|[\d,]+\s?kr/).first()).toBeVisible();
  const usd = await page.locator("main").getByText(/^\$[\d,]+$/).count();
  expect(usd).toBe(0);
});

test("keyboard only: type an airport and press Enter", async ({ page }) => {
  await page.goto("/?new=1");
  await expect(page.locator("form").getByText("From", { exact: true }).first()).toBeVisible();
  const to = page.getByPlaceholder("Anywhere (explore)");
  await to.click();
  await to.pressSequentially("lisbon", { delay: 30 });
  await page.keyboard.press("Enter");
  await expect(page.locator("form")).toContainText("LIS");
});

test("recent searches: one click repeats a past search", async ({ page }) => {
  await page.goto("/?from=OSL&to=CPH&tt=oneway&d=2026-11-19");
  await expect(page.getByText(/\d+ flights/)).toBeVisible();
  await page.getByRole("link", { name: "FlightScout" }).first().click();
  await expect(page.locator("form")).not.toContainText("CPH");
  await page.getByRole("button", { name: /Oslo → Copenhagen/ }).first().click();
  await expect(page.locator("form")).toContainText("CPH");
  await expect(page.getByText(/\d+ flights/)).toBeVisible(); // searched by itself
  await expect(page.getByRole("link", { name: "All history" })).toBeVisible();
});
