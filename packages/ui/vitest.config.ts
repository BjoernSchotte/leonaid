import { defineConfig } from "vitest/config";

export default defineConfig({
  cacheDir: "/tmp/leonaid-vite-cache",
  test: {
    // Node by default; component tests opt into jsdom per file.
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
