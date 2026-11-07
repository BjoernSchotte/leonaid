import { defineConfig } from "vitest/config";

export default defineConfig({
  cacheDir: "/tmp/leonaid-vite-cache",
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
