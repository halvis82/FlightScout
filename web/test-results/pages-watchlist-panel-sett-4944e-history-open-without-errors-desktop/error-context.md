# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: pages.spec.ts >> watchlist panel, settings and history open without errors
- Location: e2e/pages.spec.ts:20:5

# Error details

```
Error: expect(received).toEqual(expected) // deep equality

- Expected  - 1
+ Received  + 4

- Array []
+ Array [
+   "Failed to load resource: net::ERR_CONNECTION_REFUSED",
+   "Failed to load resource: net::ERR_CONNECTION_REFUSED",
+ ]
```

# Page snapshot

```yaml
- generic [active] [ref=f2e1]:
  - generic [ref=f2e2]:
    - banner [ref=f2e3]:
      - generic [ref=f2e4]:
        - link "FlightScout" [ref=f2e5] [cursor=pointer]:
          - /url: /?new=1
        - navigation [ref=f2e10]:
          - link "Search" [ref=f2e11] [cursor=pointer]:
            - /url: /
          - link "Airlines" [ref=f2e12] [cursor=pointer]:
            - /url: /airlines
        - generic [ref=f2e13]:
          - 'button "Currency: USD" [ref=f2e15]': USD
          - button "Watchlist, 0 routes" [ref=f2e18]:
            - generic [ref=f2e21]: Watchlist
          - link "Settings" [ref=f2e22] [cursor=pointer]:
            - /url: /settings
          - button "Account menu" [ref=f2e27]
    - main [ref=f2e32]:
      - generic [ref=f2e35]:
        - heading "History" [level=1] [ref=f2e36]
        - paragraph [ref=f2e37]: Every search, smart route and explore run, including ones sent by the CLI, MCP agents and watch checks.
    - complementary [aria-hidden]:
      - generic:
        - generic:
          - heading [level=2]: Watchlist
          - paragraph: Checked twice a day. Use Watch on any search or result to add one.
        - generic:
          - button: New
          - button
  - alert [ref=f2e42]
```

# Test source

```ts
  1  | import { expect, test } from "@playwright/test";
  2  | import { watchErrors } from "./helpers";
  3  | 
  4  | test("airlines directory prefills routes and opens in a new tab", async ({ page }) => {
  5  |   await page.goto("/airlines");
  6  |   await expect(page.getByText(/\d+ airlines/)).toBeVisible();
  7  |   const input = page.getByPlaceholder("From (optional)");
  8  |   await input.click();
  9  |   await input.fill("OSL");
  10 |   await page.getByRole("option").first().click();
  11 |   const to = page.getByPlaceholder("To (optional)");
  12 |   await to.click();
  13 |   await to.fill("CPH");
  14 |   await page.getByRole("option").first().click();
  15 |   const sas = page.getByRole("link", { name: /Search OSL to CPH/ }).first();
  16 |   await expect(sas).toHaveAttribute("target", "_blank");
  17 |   await expect(sas).toHaveAttribute("href", /OSL/);
  18 | });
  19 | 
  20 | test("watchlist panel, settings and history open without errors", async ({ page }) => {
  21 |   const errors = watchErrors(page);
  22 |   await page.goto("/");
  23 |   await page.getByRole("button", { name: /Watchlist/ }).first().click();
  24 |   await expect(page.getByText("Checked twice a day")).toBeVisible();
  25 |   await page.keyboard.press("Escape");
  26 |   await page.goto("/settings");
  27 |   await expect(page.getByText("Start searches from")).toBeVisible();
  28 |   await expect(page.getByText("Favorite airports and cities")).toBeVisible();
  29 |   await page.goto("/history");
> 30 |   expect(errors).toEqual([]);
     |                  ^ Error: expect(received).toEqual(expected) // deep equality
  31 | });
  32 | 
  33 | test("watch is one click for guests", async ({ page }) => {
  34 |   await page.goto("/?from=OSL&to=CPH&tt=oneway&d=2026-11-19");
  35 |   await expect(page.getByText(/\d+ flights/)).toBeVisible();
  36 |   await page.getByRole("button", { name: "Watch this search" }).click();
  37 |   await expect(page.getByText(/Watching OSL to CPH/)).toBeVisible();
  38 | });
  39 | 
  40 | test("signups are invite only", async ({ request, baseURL }) => {
  41 |   const r = await request.post("/api/auth/sign-up/email", {
  42 |     headers: { origin: baseURL! },
  43 |     data: { email: `stranger-${Date.now()}@example.com`, password: "Sup3rsecret!!x", name: "x" },
  44 |   });
  45 |   expect(r.status()).toBeGreaterThanOrEqual(400);
  46 |   expect(await r.text()).toMatch(/invite only/);
  47 | });
  48 | 
```