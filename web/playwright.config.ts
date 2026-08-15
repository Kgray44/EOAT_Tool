import { defineConfig, devices } from "@playwright/test";

const liveBaseUrl = process.env.EOAT_LIVE_BASE_URL;

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  use: {
    baseURL: liveBaseUrl ?? "http://127.0.0.1:4173",
    trace: "retain-on-failure",
  },
  webServer: liveBaseUrl
    ? undefined
    : {
        command: `"${process.execPath}" ./node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4173`,
        url: "http://127.0.0.1:4173",
        reuseExistingServer: !process.env.CI,
      },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
