import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { Kysely, sql } from "kysely";
import {
  patchPostgresSource,
  postgresAdapterEntry,
} from "../../apps/campaign-site/emdash-postgres-patch.mjs";
import {
  readPublishedCampaign,
  PublishedCampaignUnavailable,
} from "../../apps/campaign-site/src/public/published-campaign.mjs";

const entry = postgresAdapterEntry();
const source = await readFile(entry, "utf8");
const patched = patchPostgresSource(source);
for (const changed of [
  source + "\n",
  source.replace("max ?? 10", "max ?? 20"),
  patched,
])
  assert.throws(
    () => patchPostgresSource(changed),
    /EmDash PostgreSQL source changed/,
  );
// Load exactly the build transform with its real installed dependencies.
// Absolute import URLs only compensate for this in-memory module's location.
const executable = patched
  .replace('"pg"', JSON.stringify(import.meta.resolve("pg")))
  .replace(
    '"../database/pg-migration-lock.mjs"',
    JSON.stringify(
      pathToFileURL(
        resolve(dirname(entry), "../database/pg-migration-lock.mjs"),
      ).href,
    ),
  );
const { createDialect } = await import(
  `data:text/javascript;base64,${Buffer.from(executable).toString("base64")}`
);
const database = new Kysely({
  dialect: createDialect({ pool: { min: 0, max: 5 } }),
});
let release;
const released = new Promise((done) => {
  release = done;
});
const holders = [];
try {
  for (let index = 0; index < 5; index++) {
    let acquired;
    const ready = new Promise((done) => {
      acquired = done;
    });
    const holder = database.connection().execute(async (connection) => {
      await sql`SELECT 1`.execute(connection);
      acquired();
      await released;
    });
    holders.push(holder);
    await Promise.race([ready, holder]);
  }
  for (const operation of [
    () => sql`SELECT pg_sleep(5)`.execute(database),
    () =>
      readPublishedCampaign(database, "20000000-0000-4000-8000-000000000001"),
  ]) {
    const started = performance.now();
    await assert.rejects(operation);
    const elapsed = performance.now() - started;
    assert.ok(
      elapsed >= 1800 && elapsed < 4000,
      "real pool acquisition must expire within the budget",
    );
  }
  const started = performance.now();
  await assert.rejects(
    () =>
      readPublishedCampaign(database, "20000000-0000-4000-8000-000000000001"),
    PublishedCampaignUnavailable,
  );
  assert.ok(performance.now() - started < 4000);
  release();
  await Promise.all(holders);
  const recoveryStarted = performance.now();
  // Check every connection: a timed-out queued pg_sleep must never execute
  // later and consume capacity after the caller has already received failure.
  await Promise.all(
    Array.from({ length: 5 }, () => sql`SELECT 1`.execute(database)),
  );
  assert.ok(performance.now() - recoveryStarted < 1500);
  const active =
    await sql`SELECT count(*)::integer AS count FROM pg_stat_activity
    WHERE datname=current_database() AND state='active'
    AND query=${"SELECT pg_sleep(5)"}`.execute(database);
  assert.equal(active.rows[0].count, 0);
  // Server-side cancellation also covers queries outside our explicit
  // transactions. It must not merely abandon a still-running driver promise.
  await database.connection().execute(async (connection) => {
    const setting = await sql`SHOW statement_timeout`.execute(connection);
    assert.equal(setting.rows[0].statement_timeout, "5s");
    const queryStarted = performance.now();
    await assert.rejects(() => sql`SELECT pg_sleep(8)`.execute(connection), {
      code: "57014",
    });
    assert.ok(performance.now() - queryStarted >= 4500);
    assert.ok(performance.now() - queryStarted < 7000);
    // Reuse this exact connection after server cancellation.
    await sql`SELECT 1`.execute(connection);
  });
  console.log(
    "postgres-pool: exact production transform, real pool saturation/queue cancellation, server SQL cancellation and same-connection recovery passed",
  );
} finally {
  release();
  await Promise.allSettled(holders);
  await database.destroy();
}
