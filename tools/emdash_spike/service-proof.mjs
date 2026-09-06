import assert from "node:assert/strict";
import pg from "pg";
import { createStorage } from "emdash/storage/s3";

const unavailable = process.argv.includes("--database-down");
for (const [path, status, body] of [
  ["/health/live", 200, "ok"],
  [
    "/health/ready",
    unavailable ? 503 : 200,
    unavailable ? "unavailable" : "ok",
  ],
  ["/_emdash/admin/setup", 503, "CMS access is not enabled"],
  ["/_emdash/api/setup", 503, "CMS access is not enabled"],
]) {
  const response = await fetch(`http://campaign-site:3000${path}`, {
    signal: AbortSignal.timeout(4000),
    redirect: "manual",
  });
  assert.equal(response.status, status);
  assert.equal(await response.text(), body);
  assert.equal(response.headers.get("cache-control"), "no-store");
}
if (!unavailable) {
  const db = new pg.Pool({ connectionTimeoutMillis: 3000 });
  const storage = createStorage({});
  try {
    if (!process.argv.includes("--existing")) {
      await db.query(
        "CREATE TABLE service_persistence (id integer PRIMARY KEY)",
      );
      await db.query("INSERT INTO service_persistence VALUES (13)");
      await storage.upload({
        key: "service-proof.txt",
        body: Buffer.from("retained-media"),
        contentType: "text/plain",
      });
    }
    assert.equal(
      (await db.query("SELECT id FROM service_persistence")).rows[0].id,
      13,
    );
    const download = await storage.download("service-proof.txt");
    assert.equal(await new Response(download.body).text(), "retained-media");
  } finally {
    await db.end();
  }
  const forbidden = new pg.Client({
    database: "leonaid",
    connectionTimeoutMillis: 3000,
  });
  try {
    await assert.rejects(
      forbidden.connect(),
      (error) => error.code === "42501",
    );
  } finally {
    await forbidden.end();
  }
}
console.log(
  "emdash-service-proof: OK: bounded health, closed setup, scoped credentials, real adapter media and persistence",
);
