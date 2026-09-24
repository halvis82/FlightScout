import { expect, type Page } from "@playwright/test";

// 429 is ignored: back to back test runs from one IP hit the guest rate limit,
// which the app handles gracefully.
export function watchErrors(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => {
    // the local runner probe (127.0.0.1:8787) is expected to fail when it isn't running
    if (m.type() === "error" && !/127\.0\.0\.1:8787|ERR_FAILED|ERR_CONNECTION_REFUSED|CORS|status of 429/.test(m.text())) errors.push(m.text());
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
  while (await form.getByRole("button", { name: /^Remove / }).count()) {
    await form.getByRole("button", { name: /^Remove / }).first().click();
  }
}
