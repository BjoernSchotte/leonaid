/** Verify real production SPA documents and assets, including direct module links. */
import assert from "node:assert/strict";

const origin = process.argv[2];
if (!origin) throw new Error("Usage: node tools/testing/spa_routes.mjs <origin>");
const id = "10000000-0000-4000-8000-000000000001";
for (const surface of ["admin", "app"]) {
  const root = new URL(`/${surface}/`, origin);
  const response = await fetch(root);
  assert.equal(response.status, 200);
  const document = await response.text();
  assert.match(document, /<script[^>]+type="module"[^>]+src=/);
  assert.equal(response.headers.get("cache-control"), "no-store");
  for (const route of [
    "tasks", "knowledge", "materials", "inbox",
    ...["tasks", "knowledge", "materials", "inbox"].map(name => `${name}/${id}`),
    "unknown-module-route",
  ]) {
    const result = await fetch(new URL(route, root));
    assert.equal(result.status, 200, `${surface}/${route}`);
    assert.equal(await result.text(), document, `${surface}/${route}: same SPA entry`);
    assert.equal(result.headers.get("cache-control"), "no-store");
  }
  const assets = [...document.matchAll(/(?:src|href)="([^\"]+\.(?:js|css))"/g)];
  assert.ok(assets.length > 0);
  for (const [, asset] of assets) {
    const result = await fetch(new URL(asset, root));
    assert.equal(result.status, 200, asset);
    assert.ok(!(result.headers.get("content-type") ?? "").includes("text/html"), asset);
  }
  console.log(`PASS ${surface}: direct module links, client-side unknown route, actual JS/CSS, no-store HTML`);
}
const offline = await fetch(new URL("/app/offline", origin));
assert.equal(offline.status, 200);
assert.match(await offline.text(), /offline/i);
console.log("PASS PWA offline document");
