import react from "@vitejs/plugin-react";
import { configDefaults, defineConfig } from "vitest/config";

export default defineConfig({
  cacheDir: "/tmp/leonaid-vite-cache",
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    // *.real.test.tsx talk to a running Core; tools/action_admin/test.sh
    // passes the file explicitly with its environment.
    exclude: process.env.LEONAID_COMPONENT_API_BASE_URL
      ? configDefaults.exclude
      : [...configDefaults.exclude, "src/**/*.real.test.tsx"],
  },
});
