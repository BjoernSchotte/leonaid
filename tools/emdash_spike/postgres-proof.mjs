import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import pg from "pg";
import { Kysely } from "kysely";
import { createDialect } from "emdash/db/postgres";
import { runMigrations, getExactMigrationStatus } from "emdash/db";
import { provisionPostgres } from "./provision-postgres.mjs";

const admin = new pg.Pool({ connectionTimeoutMillis: 3000 });
const password = randomBytes(32).toString("hex");
const options = {
  admin,
  coreDatabase: "leonaid",
  coreRole: "leonaid",
  password,
};
try {
  if (process.argv.includes("--existing")) {
    assert.equal(
      (await admin.query("SELECT id FROM core_probe")).rows[0].id,
      42,
    );
    const previous = new pg.Pool({
      database: "emdash",
      connectionTimeoutMillis: 3000,
    });
    try {
      assert.equal(
        (await previous.query("SELECT id FROM cms_probe")).rows[0].id,
        7,
      );
    } finally {
      await previous.end();
    }
  }
  // Existing initialized Core data must survive provisioning and repeated runs.
  await admin.query(
    "CREATE TABLE IF NOT EXISTS core_probe (id integer PRIMARY KEY)",
  );
  await admin.query(
    "INSERT INTO core_probe VALUES (42) ON CONFLICT DO NOTHING",
  );
  await provisionPostgres(options);
  await provisionPostgres(options);
  const database = new Kysely({
    dialect: createDialect({
      host: process.env.PGHOST,
      user: "emdash",
      database: "emdash",
      password,
      pool: { max: 2 },
    }),
  });
  try {
    if (process.argv.includes("--existing")) {
      assert.deepEqual((await getExactMigrationStatus(database)).pending, []);
    }
    await runMigrations(database);
    await runMigrations(database);
    assert.deepEqual((await getExactMigrationStatus(database)).pending, []);
  } finally {
    await database.destroy();
  }
  const cms = new pg.Pool({
    user: "emdash",
    database: "emdash",
    password,
    connectionTimeoutMillis: 3000,
  });
  try {
    await cms.query(
      "CREATE TABLE IF NOT EXISTS cms_probe (id integer PRIMARY KEY)",
    );
    await cms.query("INSERT INTO cms_probe VALUES (7) ON CONFLICT DO NOTHING");
    assert.equal((await cms.query("SELECT id FROM cms_probe")).rows[0].id, 7);
    for (const statement of [
      "CREATE DATABASE forbidden",
      "CREATE ROLE forbidden SUPERUSER",
      "SET ROLE leonaid",
    ]) {
      await assert.rejects(
        cms.query(statement),
        (error) => error.code === "42501",
      );
    }
  } finally {
    await cms.end();
  }
  const forbidden = new pg.Client({
    user: "emdash",
    database: "leonaid",
    password,
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
  assert.equal((await admin.query("SELECT id FROM core_probe")).rows[0].id, 42);
  // Unsafe preexisting state is refused, never silently adopted.
  await admin.query("ALTER ROLE emdash CREATEDB");
  await assert.rejects(provisionPostgres(options), /unsafe_existing_cms_role/);
  await admin.query("ALTER ROLE emdash NOCREATEDB");
  await assert.rejects(
    provisionPostgres({ ...options, coreRole: "wrong" }),
    /unexpected_core_owner/,
  );
  await provisionPostgres(options);
  console.log(
    "emdash-postgres-proof: OK: real PostgreSQL, EmDash migrations, repeat provisioning, Core/CMS persistence, denied Core access/escalation, unsafe-state rejection",
  );
} finally {
  await admin.end();
}
