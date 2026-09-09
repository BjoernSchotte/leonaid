import assert from "node:assert/strict";
import pg from "pg";

async function inventory(host) {
  const db = new pg.Client({
    host,
    database: "emdash",
    user: "emdash",
    password: process.env.CMS_POSTGRES_PASSWORD,
  });
  await db.connect();
  try {
    const tables = (
      await db.query(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename",
      )
    ).rows;
    const result = {};
    for (const { tablename } of tables) {
      const rows = (
        await db.query(
          `SELECT to_jsonb(t)::text AS value FROM public.${pg.escapeIdentifier(tablename)} t ORDER BY to_jsonb(t)::text`,
        )
      ).rows;
      result[tablename] = rows.map((row) => row.value);
    }
    assert.ok(result.ec_campaign_pages.length >= 2);
    assert.ok(result.revisions.length >= 2);
    const owners = await db.query(
      "SELECT tableowner FROM pg_tables WHERE schemaname='public'",
    );
    assert.ok(owners.rows.every((row) => row.tableowner === "emdash"));
    const sequences = {};
    const sequenceNames = await db.query(
      "SELECT sequencename FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename",
    );
    for (const { sequencename } of sequenceNames.rows) {
      sequences[sequencename] = (
        await db.query(
          `SELECT last_value::text, is_called FROM public.${pg.escapeIdentifier(sequencename)}`,
        )
      ).rows;
    }
    return { tables: result, sequences };
  } finally {
    await db.end();
  }
}
try {
  assert.deepEqual(
    await inventory("restore-postgres"),
    await inventory("core-postgres"),
  );
  console.log(
    "recovery-sql: all actual CMS tables, revisions, sequence states and dedicated ownership match after pg_restore",
  );
} catch {
  console.error(
    "recovery-sql: inventory or ownership mismatch; no private row output",
  );
  process.exitCode = 1;
}
