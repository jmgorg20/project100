import { defineConfig } from "@playwright/test";

// UI tests run the built renderer in Chromium with a stand-in for the Electron bridge
// (src/renderer/lib/mockApi.ts, enabled by ?mock=1). The real Electron shell is not used.
export default defineConfig({
  testDir: "tests/ui",
  globalSetup: "./tests/ui/global-setup.ts",
  timeout: 60_000,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:4173",
    // A fake microphone (a test tone) for the voice-over recorder; no permission prompt.
    launchOptions: { args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"] },
  },
  webServer: {
    command: "npx vite preview --port 4173 --strictPort --host 127.0.0.1",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: false,
  },
});
