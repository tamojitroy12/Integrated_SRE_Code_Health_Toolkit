import { defineConfig, devices } from "@playwright/test";

// Runs against a live stack (docker compose up). Credentials come from the environment.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
  },
  projects: process.env.PLAYWRIGHT_ALL_BROWSERS
    ? [
        { name: "chromium", use: { ...devices["Desktop Chrome"] } },
        { name: "firefox", use: { ...devices["Desktop Firefox"] } },
        { name: "webkit", use: { ...devices["Desktop Safari"] } },
        { name: "mobile", use: { ...devices["Pixel 7"] } },
      ]
    : [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }, { name: "mobile", use: { ...devices["Pixel 7"] } }],
});
