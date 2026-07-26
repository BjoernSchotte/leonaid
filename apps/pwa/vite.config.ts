import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  base: "/app/",
  build: {
    outDir: "dist",
    sourcemap: true,
  },
  plugins: [react(), tailwindcss()],
});
