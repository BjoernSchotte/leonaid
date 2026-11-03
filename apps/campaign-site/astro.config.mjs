import node from "@astrojs/node";
import react from "@astrojs/react";
import { defineConfig } from "astro/config";
import emdash, { s3 } from "emdash/astro";
import { postgres } from "emdash/db";
import routeContract from "./route-contract.mjs";
import stableIdentityPatch from "./emdash-auth-patch.mjs";
import editorRevisionPatch from "./emdash-editor-patch.mjs";
import contentLogPatch from "./emdash-content-log-patch.mjs";
import postgresPatch, { cmsPoolConfig } from "./emdash-postgres-patch.mjs";
import { emdashAdminScriptHashes } from "./emdash-admin-csp.mjs";
import zodJitlessPatch from "./zod-jitless-patch.mjs";
import runtimeAllowedDomains, {
  runtimeDomainPattern,
} from "../public/runtime-allowed-domains.mjs";

export default defineConfig({
  output: "server",
  adapter: node({ mode: "standalone" }),
  build: { assets: "_campaign-assets" },
  image: { endpoint: { route: "/_emdash/image", entrypoint: undefined } },
  server: { host: true, port: 3000 },
  security: {
    // LEONAID_PUBLIC_DOMAIN is added at runtime (runtime-allowed-domains.mjs).
    allowedDomains: [
      { hostname: "localhost" },
      { hostname: "proxy" },
      runtimeDomainPattern,
    ],
    checkOrigin: true,
    actionBodySizeLimit: 64 * 1024,
    // Astro sends the Content-Security-Policy header of every rendered page
    // (campaign pages and the EmDash admin shell) because only the renderer
    // knows the sha256 hashes of the scripts and styles it inlines (island
    // hydration, small stylesheets). script-src and style-src are 'self' plus
    // those hashes; no 'unsafe-inline'. The other directives must stay
    // identical to (leonaid_headers) in infra/proxy/Caddyfile and
    // infra/pilot/Caddyfile* (tests/unit/test_csp_policy.py).
    csp: {
      algorithm: "SHA-256",
      directives: [
        "default-src 'self'",
        "base-uri 'self'",
        "connect-src 'self'",
        "font-src 'self' data:",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "frame-src 'self' https://www.google.com https://maps.google.com",
        "img-src 'self' data: blob:",
        "object-src 'none'",
      ],
      scriptDirective: { hashes: emdashAdminScriptHashes() },
    },
  },
  integrations: [
    stableIdentityPatch(),
    editorRevisionPatch(),
    contentLogPatch(),
    postgresPatch(),
    zodJitlessPatch(),
    runtimeAllowedDomains("LEONAID_PUBLIC_DOMAIN"),
    react(),
    emdash({
      // A fixed public favicon avoids the native shell resolving global CMS
      // media/settings merely to render a campaign editor's HTML document.
      admin: {
        siteName: "LeonAid",
        footerLabel: "LeonAid",
        favicon: "/favicon.svg",
      },
      // No daily request to registry.npmjs.org from the CMS server. LeonAid
      // pins EmDash in bun.lock and upgrades it through a reviewed release.
      updateCheck: false,
      // The editor toolbar injects inline scripts and styles into public
      // pages, which the strict CSP blocks. Campaigns are edited in /_emdash.
      toolbar: false,
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
      database: postgres({ pool: { ...cmsPoolConfig } }),
      storage: s3(),
      migrations: { runtime: "check", dev: "check" },
      plugins: [],
      sandboxed: [],
      mcp: false,
    }),
    routeContract(),
  ],
});
