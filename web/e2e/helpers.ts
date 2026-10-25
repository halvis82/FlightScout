import { expect, type Page } from "@playwright/test";

// 429 is ignored: back to back test runs from one IP hit the guest rate limit,
// which the app handles gracefully.
export function watchErrors(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => {
    // the local runner probe (127.0.0.1:8787) is expected to fail when it isn't running.
    // A failed resource load is judged by its URL below (the console message has none).
    if (m.type() === "error" && !/127\.0\.0\.1:8787|ERR_FAILED|ERR_CONNECTION_REFUSED|CORS|status of 429|Failed to load resource/.test(m.text())) errors.push(m.text());
  });
  page.on("response", (r) => {
    // an airline without a logo on the logo services falls back to a badge: fine
    if (r.status() >= 400 && r.status() !== 429 && !/pics\.avs\.io|images\.kiwi\.com\/airlines|127\.0\.0\.1:8787/.test(r.url())) errors.push(`${r.status()} ${r.url()}`);
  });
  return errors;
}

export async function fresh(page: Page) {
  await page.goto("/?new=1");
  await expect(page.locator("form").getByText("From", { exact: true }).first()).toBeVisible();
}

export async function pickAirport(page: Page, placeholder: RegExp | string, text: string, option: RegExp | string) {
  const input = page.getByPlaceholder(placeholder).first();
  await input.click();
  await input.fill(text);
  await page.getByRole("option").filter({ hasText: option }).first().click();
}

export async function clearFrom(page: Page) {
  const form = page.locator("form");
  // a first visit looks up the airport nearest the visitor's IP and fills it in
  // a moment later (GitHub's runners: QRO); let that land before clearing
  await page.waitForFunction(() => localStorage.getItem("fs.geoFrom") !== null, null, { timeout: 10_000 }).catch(() => {});
  await page.waitForTimeout(300);
  while (await form.getByRole("button", { name: /^Remove / }).count()) {
    await form.getByRole("button", { name: /^Remove / }).first().click();
  }
}

// A date this many days from today (YYYY-MM-DD), so searches never fall in the past.
export function inDays(n: number) {
  return new Date(Date.now() + n * 86400_000).toISOString().slice(0, 10);
}

// The next year in which this month and day (MM-DD) is still ahead, optionally
// one that also passes `ok` (e.g. a February without the 29th).
export function yearFor(mmdd: string, ok: (year: number) => boolean = () => true) {
  const soon = inDays(2);
  for (let y = new Date().getUTCFullYear(); ; y++) if (`${y}-${mmdd}` >= soon && ok(y)) return y;
}

export const isLeap = (y: number) => (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
