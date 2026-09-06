import node from "@astrojs/node";
import react from "@astrojs/react";
import { defineConfig } from "astro/config";
import emdash, { s3 } from "emdash/astro";
import { postgres } from "emdash/db";
import routeContract from "./route-contract.mjs";
import stableIdentityPatch from "./emdash-auth-patch.mjs";
import editorRevisionPatch from "./emdash-editor-patch.mjs";

export default defineConfig({
  output: "server",
  adapter: node({ mode: "standalone" }),
  build: { assets: "_campaign-assets" },
  image: { endpoint: { route: "/_emdash/image", entrypoint: undefined } },
  server: { host: true, port: 3000 },
  security: {
    allowedDomains: [{ hostname: "localhost" }, { hostname: "proxy" }],
    checkOrigin: true,
    actionBodySizeLimit: 64 * 1024,
  },
  integrations: [
    stableIdentityPatch(),
    editorRevisionPatch(),
    react(),
    emdash({
      auth: {
        type: "leonaid-core",
        entrypoint: new URL("./src/auth/leonaid-auth.ts", import.meta.url)
          .pathname,
        config: { autoProvision: false, syncRoles: false },
      },
      middleware: {
        outer: new URL("./src/closed-bootstrap.ts", import.meta.url),
      },
      // pg reads PGHOST/PGDATABASE/PGUSER/PGPASSWORD at runtime. Never bake
      // deployment secrets into Astro's serialized integration configuration.
      database: postgres({ pool: { min: 0, max: 5 } }),
      storage: s3(),
      migrations: { runtime: "check", dev: "check" },
      plugins: [],
      sandboxed: [],
      mcp: false,
    }),
    routeContract(),
  ],
});
