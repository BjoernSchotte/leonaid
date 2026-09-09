import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import pg from "pg";
import { Kysely } from "kysely";
import { createDialect } from "emdash/db/postgres";
import { runMigrations } from "emdash/db";
import { provisionPostgres } from "./provision-postgres.mjs";
import {
  installIdentityMapping,
  synchronizeExternalIdentity,
} from "../../apps/campaign-site/src/auth/identity-map.mjs";

const admin = new pg.Pool({ connectionTimeoutMillis: 3000 });
const password = randomBytes(32).toString("hex");
try {
  await provisionPostgres({
    admin,
    coreDatabase: "leonaid",
    coreRole: "leonaid",
    password,
  });
} finally {
  await admin.end();
}
const options = {
  host: process.env.PGHOST,
  user: "emdash",
  database: "emdash",
  password,
};
const database = new Kysely({ dialect: createDialect(options) });
try {
  await runMigrations(database);
} finally {
  await database.destroy();
}
const pool = new pg.Pool({ ...options, max: 5, connectionTimeoutMillis: 3000 });
const system = {
  coreUserId: "10000000-0000-4000-8000-000000000001",
  email: "system@leonaid.invalid",
  name: "Synthetic System Admin",
  role: 50,
};
const charity = {
  coreUserId: "10000000-0000-4000-8000-000000000002",
  email: "charity@leonaid.invalid",
  name: "Synthetic Charity Admin",
  role: 40,
};
const hasCode = (code) => (error) =>
  error.code === code && error.message === code;
try {
  await installIdentityMapping(pool);
  await installIdentityMapping(pool);
  await pool.query(
    "ALTER TABLE leonaid_external_identity DROP CONSTRAINT leonaid_external_identity_cms_user_id_key",
  );
  await assert.rejects(
    installIdentityMapping(pool),
    hasCode("identity_schema_mismatch"),
  );
  await pool.query(
    "ALTER TABLE leonaid_external_identity ADD UNIQUE (cms_user_id)",
  );
  await installIdentityMapping(pool);
  const wrongDatabase = new pg.Pool({ connectionTimeoutMillis: 3000 });
  try {
    await assert.rejects(
      synchronizeExternalIdentity(wrongDatabase, system),
      hasCode("cms_database_required"),
    );
  } finally {
    await wrongDatabase.end();
  }
  if (!process.argv.includes("--existing")) {
    await assert.rejects(
      synchronizeExternalIdentity(pool, charity),
      hasCode("system_admin_bootstrap_required"),
    );
    assert.equal(
      (await pool.query("SELECT count(*) FROM users")).rows[0].count,
      "0",
    );
    const concurrent = await Promise.all(
      Array.from({ length: 12 }, () =>
        synchronizeExternalIdentity(pool, system),
      ),
    );
    assert.equal(new Set(concurrent.map((item) => item.cmsUserId)).size, 1);
    const a = await synchronizeExternalIdentity(pool, charity);
    assert.notEqual(a.cmsUserId, concurrent[0].cmsUserId);
    await pool.query("CREATE TABLE mapping_proof (id text NOT NULL)");
    await pool.query("INSERT INTO mapping_proof VALUES ($1)", [a.cmsUserId]);
  }
  // On retained-volume runs, check before updating the mapped identity.
  const retained = (await pool.query("SELECT id FROM mapping_proof")).rows[0]
    .id;
  assert.equal(
    (
      await pool.query(
        "SELECT cms_user_id FROM leonaid_external_identity WHERE core_user_id=$1",
        [charity.coreUserId],
      )
    ).rows[0].cms_user_id,
    retained,
  );
  const renamed = await synchronizeExternalIdentity(pool, {
    ...charity,
    email: "renamed@leonaid.invalid",
    name: "Renamed",
    role: 50,
  });
  assert.equal(renamed.cmsUserId, retained);
  await pool.query("UPDATE users SET disabled=1 WHERE id=$1", [retained]);
  const demoted = await synchronizeExternalIdentity(pool, {
    ...charity,
    email: "renamed@leonaid.invalid",
  });
  assert.equal(demoted.role, 40);
  const row = (
    await pool.query("SELECT name,role,disabled FROM users WHERE id=$1", [
      retained,
    ])
  ).rows[0];
  assert.equal(row.role, 40);
  assert.equal(row.disabled, 0);
  assert.equal(row.name, charity.name);
  await assert.rejects(
    synchronizeExternalIdentity(pool, {
      ...system,
      email: "renamed@leonaid.invalid",
    }),
    hasCode("identity_conflict"),
  );
  await assert.rejects(
    synchronizeExternalIdentity(pool, {
      ...charity,
      coreUserId: "10000000-0000-4000-8000-000000000003",
      email: "renamed@leonaid.invalid",
    }),
    hasCode("identity_conflict"),
  );
  assert.equal(
    (await pool.query("SELECT count(*) FROM leonaid_external_identity")).rows[0]
      .count,
    "2",
  );
  assert.equal(
    (
      await pool.query(
        "SELECT email FROM users JOIN leonaid_external_identity ON cms_user_id=id WHERE core_user_id=$1",
        [system.coreUserId],
      )
    ).rows[0].email,
    system.email,
  );
  await assert.rejects(
    synchronizeExternalIdentity(pool, { ...charity, role: 10 }),
    hasCode("invalid_core_profile"),
  );
  await assert.rejects(
    pool.query("DELETE FROM users WHERE id=$1", [retained]),
    (error) => error.code === "23503",
  );
  console.log(
    "emdash-identity-map: OK: stable UUID mapping, concurrent first login, explicit admin bootstrap, email conflicts, role sync and retained state",
  );
} finally {
  await pool.end();
}
