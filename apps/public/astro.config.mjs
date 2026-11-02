import node from "@astrojs/node";
import { defineConfig } from "astro/config";
import runtimeAllowedDomains, {
  runtimeDomainPattern,
} from "./runtime-allowed-domains.mjs";

export default defineConfig({
  adapter: node({ mode: "standalone" }),
  integrations: [runtimeAllowedDomains("LEONAID_PUBLIC_DOMAIN")],
  output: "server",
  server: {
    host: true,
    port: 3000,
  },
  security: {
    // Hosts that may set Astro.url (canonical URLs, checkOrigin): local and
    // in-network test hosts plus the installation's LEONAID_PUBLIC_DOMAIN,
    // read at runtime (runtime-allowed-domains.mjs).
    allowedDomains: [
      { hostname: "localhost" },
      { hostname: "127.0.0.1" },
      { hostname: "proxy" },
      { hostname: "public" },
      runtimeDomainPattern,
    ],
    actionBodySizeLimit: 64 * 1024,
    checkOrigin: true,
    // Astro sends the page's Content-Security-Policy header itself because only
    // the renderer knows the sha256 hashes of the scripts and styles it inlines.
    // script-src and style-src are 'self' plus those hashes; no 'unsafe-inline'.
    // The other directives must stay identical to (leonaid_headers) in
    // infra/proxy/Caddyfile and infra/pilot/Caddyfile*, which only fill in this
    // policy for responses that have none (tests/unit/test_csp_policy.py).
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
    },
  },
});
