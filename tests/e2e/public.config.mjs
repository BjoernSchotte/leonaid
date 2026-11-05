import { defineConfig } from "@playwright/test";

export default defineConfig({
  // A committed test.only must not shrink a CI run (runners set CI=1).
  forbidOnly: Boolean(process.env.CI),
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
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  workers: 1,
});
