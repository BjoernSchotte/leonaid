import { defineConfig } from "@playwright/test";

const viewports = [
  ["390", { width: 390, height: 844 }],
  ["768", { width: 768, height: 1024 }],
  ["1440", { width: 1440, height: 1000 }],
];
// Layout across widths in Chromium; Firefox and WebKit at the phone width
// the PWA is built for (E-026 addendum: engine differences show at one width).
const projects = [
  ["chromium", "390"],
  ["chromium", "768"],
  ["chromium", "1440"],
  ["firefox", "390"],
  ["webkit", "390"],
];

export default defineConfig({
  // A committed test.only must not shrink a CI run (runners set CI=1).
  forbidOnly: Boolean(process.env.CI),
  expect: { timeout: 15_000 },
  fullyParallel: false,
  projects: projects.map(([browserName, width]) => ({
    name: `${browserName}-${width}`,
    use: {
      browserName,
      ignoreHTTPSErrors: true,
      viewport: Object.fromEntries(viewports)[width],
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
