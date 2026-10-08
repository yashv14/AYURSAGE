import { defineConfig } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
process.env.PHASE8_FIXTURE_FILE ||= join(
  mkdtempSync(join(tmpdir(), "ayursage-e2e-")),
  "fixtures.json",
);
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 45000,
  use: {
    baseURL: "http://127.0.0.1:5178",
    viewport: { width: 1440, height: 1000 },
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
      : {},
  },
  webServer: [
    {
      command: `${process.env.PYTHON || "python"} -m tests.browser_server`,
      cwd: "..",
      url: "http://127.0.0.1:5058/api/v1/health/live",
      timeout: 30000,
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5178 --strictPort",
      url: "http://127.0.0.1:5178",
      env: { BACKEND_PROXY_TARGET: "http://127.0.0.1:5058" },
      reuseExistingServer: false,
    },
  ],
});
