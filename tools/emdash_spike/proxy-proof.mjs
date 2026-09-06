import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { createHash } from "node:crypto";

const root = "https://proxy:8443";
const get = (path, options = {}) =>
  fetch(root + path, {
    ...options,
    redirect: "manual",
    signal: AbortSignal.timeout(5000),
  });
const hash = (bytes) => createHash("sha256").update(bytes).digest("hex");
const login = await get("/login");
assert.equal(login.status, 200);
const html = await login.text();
assert.match(html, /Bei LeonAid anmelden/);
const publicAssets = [...html.matchAll(/(?:src|href)="(\/_astro\/[^"?#]+)"/g)];
assert.ok(publicAssets.length > 0);
for (const [, path] of publicAssets) {
  const response = await get(path);
  assert.equal(response.status, 200, path);
  assert.ok(!response.headers.get("content-type")?.includes("text/html"));
}

if (process.argv.includes("--cms-stopped")) {
  assert.equal((await get("/_emdash/admin/setup")).status, 502);
  console.log("emdash-proxy-proof: OK: public login/assets survive CMS outage");
} else {
  const inventory = JSON.parse(
    await readFile("dist/route-inventory.json", "utf8"),
  );
  assert.ok(inventory.some((route) => route.pattern === "/_emdash/image"));
  assert.ok(!inventory.some((route) => route.pattern === "/_image"));
  const files = await readdir("dist/client/_campaign-assets", {
    recursive: true,
  });
  const assets = files.filter((path) =>
    /\.(js|css|woff2?|png|svg)$/.test(path),
  );
  assert.ok(assets.some((path) => path.endsWith(".js")));
  assert.ok(assets.some((path) => path.endsWith(".css")));
  for (const path of assets) {
    const response = await get(`/_campaign-assets/${path}`);
    assert.equal(response.status, 200, path);
    assert.equal(
      hash(Buffer.from(await response.arrayBuffer())),
      hash(await readFile(`dist/client/_campaign-assets/${path}`)),
      path,
    );
  }
  for (const path of [
    "/_emdash/admin/setup",
    "/_emdash/api/setup",
    "/_emdash/image?href=test",
    "/campaigns/test/",
  ]) {
    const response = await get(path);
    assert.equal(response.status, 503, path);
    assert.equal(await response.text(), "CMS access is not enabled");
  }
  // This proves dispatch only, not ordering or SEO content correctness.
  for (const path of [
    "/_image",
    "/robots.txt",
    "/sitemap.xml",
    "/_actions/missing",
  ]) {
    const response = await get(path);
    assert.notEqual(response.status, 502, path);
    assert.notEqual(await response.text(), "CMS access is not enabled", path);
  }
  console.log(
    `emdash-proxy-proof: OK: ${assets.length} CMS assets byte-verified, public assets, image namespace, setup denial and route dispatch`,
  );
}
