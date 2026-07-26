import { defineConfig } from "@playwright/test";

export default defineConfig({
  expect: { timeout: 15_000 },
  fullyParallel: false,
  projects: ["chromium", "firefox", "webkit"].map((browserName) => ({
    name: browserName,
    use: {
      browserName,
      ignoreHTTPSErrors: true,
      viewport: { width: 390, height: 844 },
    },
  })),
  testDir: ".",
  timeout: 60_000,
  use: {
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  workers: 1,
});
