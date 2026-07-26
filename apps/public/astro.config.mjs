import node from "@astrojs/node";
import { defineConfig } from "astro/config";

export default defineConfig({
  adapter: node({ mode: "standalone" }),
  output: "server",
  server: {
    host: true,
    port: 3000,
  },
  security: {
    checkOrigin: true,
  },
});
