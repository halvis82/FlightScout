import { expect, test } from "@playwright/test";

// No page may scroll sideways on a phone.
test.use({ viewport: { width: 390, height: 844 } });

for (const path of ["/?new=1", "/settings", "/airlines", "/history", "/trip", "/watches", "/?from=SAN&tt=multicity"]) {
  test(`no horizontal scroll on ${path}`, async ({ page }) => {
    await page.goto(path);
    await page.waitForLoadState("networkidle").catch(() => {});
    const width = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(width).toBeLessThanOrEqual(392);
  });
}

test("phones reach Airlines and can swap From and To", async ({ page }) => {
  await page.goto("/?from=OSL&to=CPH&tt=oneway");
  await expect(page.getByRole("button", { name: "Swap origin and destination" })).toBeVisible();
  await page.getByRole("link", { name: "Airlines" }).click();
  await expect(page).toHaveURL(/\/airlines/);
});
