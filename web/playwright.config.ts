import { defineConfig, devices } from "@playwright/test";

// Browser tests against the real service (web/tests/server.py: the API serving the built app, and a
// worker with the stand-in engine). Phones first; one desktop run checks the wider layout.
const PORT = 4180;
export default defineConfig({
  testDir: "tests",
  globalSetup: "./tests/global-setup.ts",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "retain-on-failure" },
  projects: [
    { name: "phone", use: { ...devices["Pixel 7"] } },
    { name: "small-phone", use: { viewport: { width: 360, height: 740 }, isMobile: true, hasTouch: true, deviceScaleFactor: 3,
      userAgent: devices["Pixel 7"].userAgent }, testMatch: /layout\.spec/ },
    { name: "desktop", use: { ...devices["Desktop Chrome"] }, testMatch: /layout\.spec/ },
  ],
  webServer: {
    command: `python3 tests/server.py --port ${PORT} --data tests/.data`,
    url: `http://127.0.0.1:${PORT}/healthz`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
