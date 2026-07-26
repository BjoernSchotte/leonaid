import { defineConfig } from "@playwright/test";

const viewports = [
  ["390", { width: 390, height: 844 }],
  ["768", { width: 768, height: 1024 }],
  ["1440", { width: 1440, height: 1000 }],
];
const browsers = ["chromium", "firefox", "webkit"];

export default defineConfig({
  expect: { timeout: 15_000 },
  fullyParallel: false,
  projects: browsers.flatMap((browserName) =>
    viewports.map(([width, viewport]) => ({
      name: `${browserName}-${width}`,
      use: {
        browserName,
        ignoreHTTPSErrors: true,
        viewport,
      },
    })),
  ),
  testDir: ".",
  timeout: 60_000,
  use: {
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  workers: 1,
});
