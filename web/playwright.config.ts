import { defineConfig, devices } from "@playwright/test";
import os from "node:os";
import path from "node:path";

// E2E_BASE_URL=https://flightscout-app.vercel.app npx playwright test
export default defineConfig({
  testDir: "e2e",
  // outside the repo: iCloud synced folders break Playwright's artifact writes
  outputDir: path.join(os.tmpdir(), "flightscout-e2e"),
  timeout: 120_000,
  expect: { timeout: 60_000 },
  retries: 1,
  reporter: [["list"]],
  use: { baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000", trace: "retain-on-failure", colorScheme: "dark" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } } },
    { name: "mobile", use: { ...devices["Pixel 7"] }, grep: /@mobile/ },
  ],
});
