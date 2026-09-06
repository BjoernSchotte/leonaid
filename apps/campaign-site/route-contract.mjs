import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";

// These upstream root routes are deliberately NOT routed to the CMS by Caddy.
// Public SEO remains owned by apps/public; internal health is not exposed.
const internalOnly = new Set([
  "/robots.txt",
  "/sitemap.xml",
  "/sitemap-[collection].xml",
  "/health/live",
  "/health/ready",
  "/404",
  // Astro injects this endpoint even when no deferred server island is used.
  // CMS templates must not use server:defer until it has a dedicated namespace.
  "/_server-islands/[name]",
  // No public OAuth provider or MCP discovery is part of this integration.
  "/.well-known/oauth-protected-resource",
  "/.well-known/oauth-authorization-server/_emdash",
]);

export default function routeContract() {
  let output;
  let inventory;
  return {
    name: "leonaid-campaign-route-contract",
    hooks: {
      "astro:config:done": ({ config }) => {
        output = new URL("route-inventory.json", config.outDir);
        assert.equal(config.build.assets, "_campaign-assets");
        assert.equal(config.image.endpoint.route, "/_emdash/image");
      },
      "astro:routes:resolved": ({ routes }) => {
        inventory = routes.map(({ pattern }) => {
          const exposed =
            pattern.startsWith("/_emdash/") ||
            pattern.startsWith("/campaigns/");
          assert.ok(
            exposed || internalOnly.has(pattern),
            `Unassigned CMS route: ${pattern}`,
          );
          return { pattern, exposed };
        });
        assert.ok(
          inventory.some(({ pattern }) => pattern === "/_emdash/image"),
        );
      },
      "astro:build:done": async () => {
        assert.ok(inventory?.length);
        await writeFile(output, JSON.stringify(inventory, null, 2) + "\n");
      },
    },
  };
}
