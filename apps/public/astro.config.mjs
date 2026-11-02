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
