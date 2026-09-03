import { defineConfig } from "@playwright/test";

import baseConfig from "./pwa.config.mjs";

export default defineConfig({
  ...baseConfig,
  projects: [
    {
      name: "chromium-pdf",
      use: {
        browserName: "chromium",
        // The default headless shell cannot render the native PDF viewer.
        channel: "chromium",
        ignoreHTTPSErrors: true,
        viewport: { width: 1440, height: 1000 },
      },
    },
  ],
  testMatch: "documents.spec.mjs",
});
