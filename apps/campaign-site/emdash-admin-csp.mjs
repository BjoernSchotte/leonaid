import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

export function adminRouteSource() {
  const require = createRequire(import.meta.url);
  // emdash/package.json is not exported; resolve the main entry instead.
  const packageRoot = dirname(dirname(require.resolve("emdash")));
  return readFileSync(join(packageRoot, "src/astro/routes/admin.astro"), "utf8");
}

/**
 * The pinned EmDash admin shell (/_emdash) carries one `<script is:inline>`
 * that sets the light/dark mode before the first paint. Astro hashes only the
 * scripts it processes, so this one needs an explicit CSP hash. The script is
 * static, so its hash is a build-time constant; no 'unsafe-inline' is needed.
 */
export function adminInlineScriptHashes(source) {
  assert.equal(
    createHash("sha256").update(source).digest("hex"),
    "8ffb84a6ee297983917c8f56b6678bc4b7b05c627a3a214759249717b130ed1a",
    "EmDash admin shell changed; re-review its inline scripts for the CSP",
  );
  const scripts = [
    ...source.matchAll(/<script is:inline>([\s\S]*?)<\/script>/g),
  ].map((match) => match[1]);
  assert.equal(scripts.length, 1, "EmDash admin shell inline scripts");
  assert.equal(
    [...source.matchAll(/<script\b/g)].length,
    scripts.length,
    "EmDash admin shell has a script the CSP does not cover",
  );
  return scripts.map(
    (script) =>
      `sha256-${createHash("sha256").update(script).digest("base64")}`,
  );
}

export function emdashAdminScriptHashes() {
  return adminInlineScriptHashes(adminRouteSource());
}
