import { defineConfig } from "@playwright/test";

export default defineConfig({
  // A committed test.only must not shrink a CI run (runners set CI=1).
  forbidOnly: Boolean(process.env.CI),
  expect: { timeout: 15_000 },
  fullyParallel: false,
  testDir: "tests/e2e",
  timeout: 60_000,
  use: {
    actionTimeout: 15_000,
    ignoreHTTPSErrors: true,
    navigationTimeout: 30_000,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  workers: 1,
});
