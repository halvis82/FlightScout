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

test("watch this search saves once, even when clicked repeatedly, and then shows Watching", async ({ page }) => {
  await page.goto("/?from=OSL&to=CPH&tt=oneway&d=2026-11-19");
  await expect(page.getByText(/\d+ flights/)).toBeVisible();
  const btn = page.getByRole("button", { name: "Watch this search" });
  await btn.click({ clickCount: 3 }); // triple click
  await btn.click({ force: true, timeout: 1000 }).catch(() => {}); // and again while saving (it may already be "Watching")
  await expect(page.getByRole("link", { name: /Watching/ })).toBeVisible();
  const n = await page.evaluate(async () => (await (await fetch("/api/v1/watches")).json()).length ?? 0).catch(() => null);
  // guests keep watches in the browser: count them there
  const local = await page.evaluate(() => {
    try {
      return (JSON.parse(localStorage.getItem("fs.guest.watches") ?? "[]") as unknown[]).length;
    } catch {
      return null;
    }
  });
  expect(local ?? n).toBeLessThanOrEqual(1);
  // reload: still recognized as watched
  await page.reload();
  await expect(page.getByRole("link", { name: /Watching/ })).toBeVisible();
});

test("favorite star double click does not flip twice", async ({ page }) => {
  await page.goto("/?from=SAN&tt=roundtrip&d=2026-11-06&r=2026-11-13");
  const star = page.locator("section").getByRole("button", { name: /Add .* to favorites/ }).first();
  await expect(star).toBeVisible({ timeout: 30_000 });
  await star.dblclick();
  await expect(page.locator("section").getByRole("button", { name: /Remove .* from favorites/ }).first()).toBeVisible();
});

test("multi city: switching clears old results, and it can be watched", async ({ page }) => {
  await page.goto("/?from=OSL&to=CPH&tt=oneway&d=2026-11-19");
  await expect(page.getByText(/\d+ flights/)).toBeVisible();
  await page.getByRole("radio", { name: "Multi-city" }).click();
  await expect(page.getByText(/\d+ flights/)).toHaveCount(0);
  const legs = [
    { to: ["CPH"], date: "2026-11-19", flex: 1 },
    { to: ["OSL"], date: "2026-11-24", flex: 1 },
  ];
  await page.goto(`/?from=OSL&tt=multicity&d=2026-11-19&ml=${encodeURIComponent(JSON.stringify(legs))}`);
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByText("OSL → CPH → OSL")).toBeVisible({ timeout: 90_000 });
  await expect(page.getByRole("button", { name: "Watch this search" })).toBeVisible({ timeout: 90_000 });
});

// The way people actually get there: a round trip search (with smart routes
// still running), then switching to multi city and editing it in the form.
test("multi city after a round trip: edit the form and Search shows results", async ({ page }) => {
  test.setTimeout(240_000);
  await page.goto("/?from=LAX&to=DPS&d=2027-03-18&r=2027-03-29&tt=roundtrip&smart=1");
  await expect(page.getByText(/\d+ flights/)).toBeVisible({ timeout: 120_000 });
  await page.getByRole("radio", { name: "Multi-city" }).click();
  const pick = async (input: import("@playwright/test").Locator, code: string) => {
    await input.click();
    await input.fill(code);
    await page.locator("[role=listbox] [role=option]").first().click();
    await page.keyboard.press("Escape");
  };
  await page.getByRole("button", { name: "Remove LAX" }).first().click();
  await pick(page.locator("form input").first(), "CUN");
  await page.getByRole("button", { name: "Remove DPS" }).first().click();
  await pick(page.getByPlaceholder("Next stop").first(), "MLM");
  // the return leg the round trip left behind becomes Tijuana
  await page.getByRole("button", { name: "Remove LAX" }).first().click();
  await pick(page.getByPlaceholder("Next stop").first(), "TIJ");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByText("CUN → MLM → TIJ")).toBeVisible({ timeout: 180_000 });
  await expect(page.getByText(/\d+ flights/)).toBeVisible();
});

// Watching works before searching, a watched search shows as watched (never
// "Watch this search" again), and the watch page reads well: a readable URL
// and the full list of flights, not just one.
test("watch before searching, stays watched, readable watch page with all flights", async ({ page }) => {
  test.setTimeout(240_000);
  const legs = [
    { to: ["MLM"], date: "2026-12-30", flex: 0 },
    { to: ["TIJ"], date: "2027-01-09", flex: 1 },
  ];
  await page.goto(`/?from=CUN&tt=multicity&d=2026-12-30&ml=${encodeURIComponent(JSON.stringify(legs))}`);
  // no search has run, the watch button is already there
  await page.getByRole("button", { name: "Watch this search" }).click();
  const watching = page.getByRole("link", { name: /Watching/ });
  await expect(watching).toBeVisible({ timeout: 30_000 });
  // searching the same thing keeps it watched
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByText("CUN → MLM → TIJ").first()).toBeVisible({ timeout: 180_000 });
  await expect(page.getByRole("button", { name: "Watch this search" })).toHaveCount(0);
  await expect(watching).toBeVisible();
  // the watch page
  await page.waitForTimeout(1600); // past the double click guard on the Watching link
  await watching.click();
  await expect(page).toHaveURL(/\/watches\/cun-mlm-tij-2026-12-30/);
  await expect(page.getByText("Flights for this multi city trip")).toBeVisible();
  await expect(page.getByText(/\d+ flights/)).toBeVisible({ timeout: 180_000 });
});

test("airlines tab marks airlines searched directly, everywhere or only locally", async ({ page }) => {
  await page.goto("/airlines");
  await expect(page.getByText(/\d+ airlines/)).toBeVisible();
  await page.getByText("Only airlines FlightScout searches directly").click();
  await expect(page.getByText("Included in FlightScout searches").first()).toBeVisible();
  await expect(page.getByText("Included in local FlightScout searches").first()).toBeVisible();
});
