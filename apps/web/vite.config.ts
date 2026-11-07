import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

import { ADMIN_BASE } from "../../packages/ui/src/lib/base-paths";

export default defineConfig({
  base: ADMIN_BASE,
  build: {
    outDir: "dist",
    sourcemap: true,
  },
  plugins: [react(), tailwindcss()],
});
