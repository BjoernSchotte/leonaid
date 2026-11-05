import { defineConfig } from "@playwright/test";

export default defineConfig({
  // A committed test.only must not shrink a CI run (runners set CI=1).
  forbidOnly: Boolean(process.env.CI),
  expect: { timeout: 15_000 },
  fullyParallel: false,
  outputDir:
    process.env.LEONAID_DOCS_TEST_OUTPUT ?? "../../.artifacts/docs/results",
  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium" },
    },
  ],
  reporter: "line",
  testDir: "tests/browser",
  timeout: 90_000,
  use: {
    baseURL: process.env.LEONAID_DOCS_BASE_URL,
    reducedMotion: "reduce",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  workers: 1,
});
