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
    allowedDomains: [
      { hostname: "localhost" },
      { hostname: "127.0.0.1" },
      { hostname: "proxy" },
    ],
    actionBodySizeLimit: 64 * 1024,
    checkOrigin: true,
  },
});
