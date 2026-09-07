import assert from "node:assert/strict";

assert.equal((await fetch("http://api:8000/health/live")).status, 200);
const readiness = await (await fetch("http://api:8000/health/ready")).json();
assert.equal(readiness.checks.postgres.status, "ready");
for (let attempt = 0; attempt < 40; attempt++) {
  try {
    if ((await fetch("http://campaign-site:3000/health/live")).status === 200)
      break;
  } catch {}
  await new Promise((resolve) => setTimeout(resolve, 250));
}
assert.equal(
  (await fetch("http://campaign-site:3000/health/live")).status,
  200,
);
for (const path of [
  "/health/ready",
  "/campaigns/synthetic-operator/",
  "/campaigns/synthetic-operator/?_action=createPublicOrder",
  "/_emdash/admin",
  "/_emdash/api/setup",
  "/_emdash/api/content/campaign_pages",
]) {
  for (const method of ["GET", "HEAD", "POST"]) {
    const response = await fetch(`http://campaign-site:3000${path}`, {
      method,
      redirect: "manual",
    });
    assert.equal(response.status, 503, `${method} ${path}`);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(response.headers.get("retry-after"), "60");
    assert.equal(response.headers.get("location"), null);
  }
}
console.log(
  "migration-traffic: CMS content/editor/setup/order/readiness closed across methods; Core liveness and real PostgreSQL remain available (Twenty/RustFS not started in this isolated proof)",
);
