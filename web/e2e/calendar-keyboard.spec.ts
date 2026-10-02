import { expect, test } from "@playwright/test";

test("calendar accepts month and day typing, arrows and return editing @mobile", async ({ page }) => {
  await page.goto("/?from=SAN&tt=roundtrip&d=2027-10-15&r=2027-10-22");
  await page.getByRole("button", { name: /^Departure:.*Open calendar/ }).click();
  const dialog = page.getByRole("dialog", { name: "Choose dates" });
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('[data-date="2027-10-15"]')).toBeFocused();
  await page.keyboard.type("dec");
  await expect(page.getByRole("button", { name: /^Departure:.*Dec 15.*Open calendar/ })).toBeVisible();
  await page.keyboard.type("23");
  await expect(dialog.locator('[data-date="2027-12-23"]')).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(dialog.locator('[data-date="2027-12-24"]')).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(dialog.locator('[data-date="2027-12-31"]')).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(dialog.locator('[data-date="2028-01-01"]')).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(dialog.getByText("Pick return", { exact: true })).toBeVisible();
  await page.keyboard.type("19");
  await expect(page.getByRole("button", { name: /^Return:.*Jan 19.*Open calendar/ })).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(dialog).not.toBeVisible();
});

test("one-way typing handles full month names, invalid days and all arrow directions @mobile", async ({ page }) => {
  await page.goto("/?from=SAN&tt=oneway&d=2027-01-31");
  await page.getByRole("button", { name: /^Departure:.*Open calendar/ }).click();
  const dialog = page.getByRole("dialog", { name: "Choose dates" });
  await expect(dialog.locator('[data-date="2027-01-31"]')).toBeFocused();
  await expect(dialog.getByRole("textbox")).toHaveCount(0);
  await page.keyboard.type("february");
  await expect(dialog.locator('[data-date="2027-02-28"]')).toBeFocused();
  await page.keyboard.type("31");
  await expect(page.getByRole("button", { name: /^Departure:.*Feb 3.*Open calendar/ })).toBeVisible();
  await page.keyboard.press("ArrowLeft");
  await expect(dialog.locator('[data-date="2027-02-02"]')).toBeFocused();
  await page.keyboard.press("ArrowUp");
  await expect(dialog.locator('[data-date="2027-01-26"]')).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("button", { name: /^Departure:.*Jan 26.*Open calendar/ })).toBeVisible();
});

test("trip and flexibility controls have larger hit targets without mobile overflow @mobile", async ({ page }) => {
  await page.goto("/?from=SAN&tt=roundtrip&d=2027-10-15&r=2027-10-22");
  for (const name of ["Round trip", "One way", "Multi-city"]) {
    const button = page.getByRole("radio", { name, exact: true });
    await expect(button).toBeVisible();
    expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  }
  for (const field of ["Departure", "Return"]) {
    for (const days of [0, 1, 2, 3, 7]) {
      const button = page.getByRole("button", { name: `${field}: ${days ? `plus or minus ${days} days` : "exact date"}`, exact: true });
      expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(40);
      await button.click();
      await expect(button).toHaveAttribute("aria-pressed", "true");
    }
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});
