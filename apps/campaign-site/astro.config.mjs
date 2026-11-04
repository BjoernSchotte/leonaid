import node from "@astrojs/node";
import react from "@astrojs/react";
import { defineConfig, fontProviders } from "astro/config";
import emdash, { s3 } from "emdash/astro";
import { postgres } from "emdash/db";
import routeContract from "./route-contract.mjs";
import stableIdentityPatch from "./emdash-auth-patch.mjs";
import editorRevisionPatch from "./emdash-editor-patch.mjs";
import contentLogPatch from "./emdash-content-log-patch.mjs";
import postgresPatch, { cmsPoolConfig } from "./emdash-postgres-patch.mjs";
import { emdashAdminScriptHashes } from "./emdash-admin-csp.mjs";
import zodJitlessPatch from "./zod-jitless-patch.mjs";
import { hiddenAdminNavItems } from "./src/auth/campaign-manifest.mjs";
import runtimeAllowedDomains, {
  runtimeDomainPattern,
} from "../public/runtime-allowed-domains.mjs";

// The EmDash admin reads its font from --font-emdash. EmDash's default is
// Noto Sans downloaded from Google Fonts at build time; `fonts: false` below
// turns that off, and this entry self-hosts Barlow (the Leitsystem face,
// latin subset) from @fontsource for the same variable instead. No Google
// Fonts request, no patch of the EmDash bundle.
// Weights 400–900 in both styles: the admin stylesheet also uses 800, 900
// and italic, which would otherwise be synthesized. <Font> is rendered
// without preload, so a browser fetches only the faces a page uses.
const barlowFile = (weight, style) =>
  `@fontsource/barlow/files/barlow-latin-${weight}-${style}.woff2`;

// Admin logo: the Lions "L" on Lions blue (as in the public header), inline
// so it needs no extra route; img-src allows data: URLs. EmDash renders it
// as an <img>, which cannot read CSS variables or currentColor, so the
// colours are the hex values the tokens approximate: #00338d = --lions-blue,
// #ebb700 = --lions-gold (packages/ui/src/styles/leitsystem.css).
const adminLogo = `data:image/svg+xml,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 28 28"><rect width="28" height="28" rx="7" fill="#00338d"/><path d="M9 6h4v12h8v4H9z" fill="#ebb700"/></svg>',
)}`;

export default defineConfig({
  output: "server",
  fonts: [
    {
      provider: fontProviders.local(),
      name: "Barlow",
      cssVariable: "--font-emdash",
      fallbacks: ["ui-sans-serif", "system-ui", "sans-serif"],
      options: {
        variants: [400, 500, 600, 700, 800, 900].flatMap((weight) =>
          ["normal", "italic"].map((style) => ({
            weight,
            style,
            src: [barlowFile(weight, style)],
          })),
        ),
      },
    },
  ],
  adapter: node({ mode: "standalone" }),
  // "never": Astro writes every stylesheet, including the scoped <style>
  // blocks of .astro components, to an external file instead of inlining
  // small ones as <style> elements. The pages carry no <style> element.
  build: { assets: "_campaign-assets", inlineStylesheets: "never" },
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
      fonts: false,
      admin: {
        logo: adminLogo,
        siteName: "LeonAid",
        footerLabel: "LeonAid",
        favicon: "/favicon.svg",
        hiddenNavItems: [...hiddenAdminNavItems],
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
