import { expect, test } from "@playwright/test";
import { clearFrom, fresh, pickAirport, inDays } from "./helpers";

test.describe("explore", () => {
  test("appears with only a From, fills fast, and a map dot searches that city", async ({ page }) => {
    await fresh(page);
    await clearFrom(page);
    await pickAirport(page, /Where from|Add airport/, "san diego", "San Diego");
    await expect(page.getByText(/Cheapest places from/)).toBeVisible();
    const rows = page.locator("section .cursor-pointer");
    await expect.poll(() => rows.count(), { timeout: 30_000 }).toBeGreaterThan(30);
    // labels, full prices (never "$1k")
    await expect.poll(() => page.locator("[data-label]:not(.fs-dot)").count()).toBeGreaterThan(10);
    const labels = await page.locator("[data-label]:not(.fs-dot)").allInnerTexts();
    expect(labels.some((l) => /\$\d/.test(l))).toBe(true);
    expect(labels.some((l) => /\dk\b/i.test(l))).toBe(false);
    // zooming reveals more labels
    const visible = () => page.locator("[data-label]:not(.fs-dot)").count();
    const before = await visible();
    await page.getByRole("button", { name: "Zoom in" }).click();
    await page.getByRole("button", { name: "Zoom in" }).click();
    await expect.poll(visible).toBeGreaterThanOrEqual(before);
    // one click on a list row searches it
    await rows.first().locator(".truncate").first().click();
    await expect(page.getByText(/[1-9]\d* flights/).first()).toBeVisible({ timeout: 60_000 });
  });

  test("any dates keeps the trip length: a weekend lists no week long trips", async ({ page }) => {
    await page.goto(`/?from=SAN&tt=roundtrip&d=${inDays(33)}&r=${inDays(35)}`);
    const rows = page.locator("section .cursor-pointer");
    await expect.poll(() => rows.count(), { timeout: 30_000 }).toBeGreaterThan(5);
    await page.getByRole("radio", { name: "Any dates" }).click();
    const nights = await rows.evaluateAll((els) => els.map((e) => Number(/(\d+) nights/.exec(e.textContent ?? "")?.[1] ?? 0)));
    expect(nights.filter((n) => n > 3), "trips longer than 2 nights ± 1").toEqual([]);
  });

  test("price slider and date toggle filter the list", async ({ page }) => {
    await page.goto(`/?from=SAN&tt=roundtrip&d=${inDays(33)}&r=${inDays(40)}`);
    const rows = page.locator("section .cursor-pointer");
    await expect.poll(() => rows.count(), { timeout: 30_000 }).toBeGreaterThan(20);
    await page.getByRole("radio", { name: /Around/ }).click();
    await page.getByRole("radio", { name: "Any dates" }).click();
    // the list refreshes for the new mode: measure it once it is populated again
    await expect.poll(() => rows.count(), { timeout: 30_000 }).toBeGreaterThan(20);
    // more places keep streaming in (36, then 124 on GitHub): measure once the list stops growing
    let n = 0;
    await expect.poll(async () => n === (n = await rows.count()), { timeout: 90_000, intervals: [3_000] }).toBe(true);
    const slider = page.getByRole("slider", { name: "Maximum price" }).first();
    await slider.evaluate((el: HTMLInputElement) => {
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      set.call(el, String(Math.round((Number(el.min) + Number(el.max)) / 4)));
      el.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await expect.poll(() => rows.count()).toBeLessThan(n);
  });

  test("clearing the destination returns to explore @mobile", async ({ page }) => {
    await page.goto(`/?from=OSL&to=CPH&tt=oneway&d=${inDays(45)}`);
    await expect(page.getByText(/[1-9]\d* flights/).first()).toBeVisible();
    await page.getByRole("button", { name: "Remove CPH" }).click();
    await expect(page.getByText(/Cheapest places from/)).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  });
});
