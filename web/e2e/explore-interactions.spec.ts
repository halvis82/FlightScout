import { expect, test } from "@playwright/test";

test("map labels stay anchored on hover and Around honors exact dates", async ({ page }) => {
  const offer = { origin: "SAN", destination: "CDG", city: "Paris", price: 600, currency: "USD", departure: "2027-10-15", return_date: "2027-10-22", source: "google", lat: 49, lon: 2.5 };
  await page.route("https://tiles.openfreemap.org/styles/**", (route) => route.fulfill({ json: { version: 8, sources: {}, layers: [] } }));
  await page.route("**/explore/cached?**", (route) => route.fulfill({ json: { items: [{ ...offer, price: 100, departure: "2027-10-13" }] } }));
  await page.route("**/explore", (route) => route.fulfill({ json: { items: [offer, { ...offer, destination: "ORY", city: "Orly", price: 700, lon: 12.5 }] } }));
  await page.goto("/?from=SAN&tt=roundtrip&d=2027-10-15&r=2027-10-22");
  await page.getByRole("radio", { name: /Around/ }).click();
  const label = page.locator('[data-label]:not(.fs-dot)').filter({ hasText: "Paris" });
  await expect(label).toHaveText("Paris $600");
  // Wait for initial map fitting to settle before comparing hover positions.
  await page.waitForTimeout(800);
  const before = (await label.boundingBox())!;
  for (const fraction of [0.2, 0.5, 0.8, 0.3]) {
    await page.mouse.move(before.x + before.width * fraction, before.y + before.height / 2);
    expect(await label.boundingBox()).toEqual(before);
  }
  const dot = page.locator('.fs-dot').filter({ hasText: "Orly" });
  const dotBefore = (await dot.boundingBox())!;
  await dot.hover();
  expect(await dot.boundingBox()).toEqual(dotBefore);
  await expect(dot.locator("span")).toBeVisible();
  const rows = page.locator("section .cursor-pointer");
  await expect(rows.filter({ hasText: "Paris" })).toContainText("$600");
});

test("Around uses separate departure and return windows, then restores Any dates @mobile", async ({ page }) => {
  const base = { origin: "SAN", price: 600, currency: "USD", source: "google", lat: 49, lon: 2.5 };
  const items = [
    { ...base, destination: "CDG", city: "Paris", departure: "2027-10-15", return_date: "2027-10-22" },
    { ...base, destination: "LHR", city: "London", departure: "2027-10-16", return_date: "2027-10-22" },
    { ...base, destination: "FRA", city: "Frankfurt", departure: "2027-10-15", return_date: "2027-10-24" },
    { ...base, destination: "FCO", city: "Rome", departure: "2027-10-17", return_date: "2027-10-22" },
  ];
  await page.route("https://tiles.openfreemap.org/styles/**", (route) => route.fulfill({ json: { version: 8, sources: {}, layers: [] } }));
  await page.route("**/explore/cached?**", (route) => route.fulfill({ json: { items } }));
  await page.route("**/explore", (route) => route.fulfill({ json: { items } }));
  await page.goto("/?from=SAN&tt=roundtrip&d=2027-10-15&r=2027-10-22");
  const rows = page.locator("section .cursor-pointer");
  await expect(rows).toHaveCount(4);
  await page.getByRole("radio", { name: /Around/ }).click();
  await expect(rows).toHaveCount(1);
  await page.getByRole("button", { name: "Departure: plus or minus 1 days", exact: true }).click();
  await expect(rows).toHaveCount(2);
  await expect(rows.filter({ hasText: "London" })).toBeVisible();
  await page.getByRole("button", { name: "Return: plus or minus 2 days", exact: true }).click();
  await expect(rows).toHaveCount(3);
  await expect(rows.filter({ hasText: "Frankfurt" })).toBeVisible();
  await expect(rows.filter({ hasText: "Rome" })).toHaveCount(0);
  await page.getByRole("radio", { name: "Any dates", exact: true }).click();
  await expect(rows).toHaveCount(4);
});
