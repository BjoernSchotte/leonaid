import pg from "pg";
import { Kysely, sql } from "kysely";
import { createDialect } from "emdash/db/postgres";
import {
  getExactMigrationStatus,
  MIGRATION_NAMES,
  runMigrations,
} from "emdash/db";
import { createStorage } from "emdash/storage/s3";
import { provisionPostgres } from "./provision-postgres.mjs";
import { installIdentityMapping } from "./auth/identity-map.mjs";
import {
  armBootstrap,
  inspectBootstrap,
  rearmExpiredBootstrap,
} from "./bootstrap-control.mjs";
import { requireCampaignSchema } from "./install-campaign-schema.mjs";
import { requireCampaignBindings } from "./auth/campaign-bindings.mjs";
import { requireCampaignMedia } from "./auth/campaign-media.mjs";
import { cmsMaintenanceClosed } from "./cms-maintenance.mjs";

// Image-owned production provisioning operator (./leonaid pilot-cms-provision,
// specs/multi-domain R11). It never starts HTTP, never prints credentials or
// SQL errors, and every mode is safe to repeat:
//   database  role, database and grants (operator credentials), then the
//             upstream EmDash migrations of an empty database and the identity
//             mapping (CMS credentials). An existing database must already
//             carry exactly this release's migrations: upgrades belong to the
//             reviewed migration controller, never to provisioning.
//   arm UUID  one-time setup grant for the designated Core System Admin.
//   status    read-only state of every step, one "key=value" line each.
// The campaign schema itself is installed by cms-migration-operator.mjs
// ("install") under closed CMS traffic.
const bootstrapDirectory = "/app/bootstrap-state";
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

class Refused extends Error {}

function cmsCredentials() {
  if (
    process.env.PGUSER !== "emdash" ||
    process.env.PGDATABASE !== "emdash" ||
    !process.env.PGHOST ||
    !process.env.PGPASSWORD
  )
    throw new Refused("cms_credentials_required");
  return {
    host: process.env.PGHOST,
    user: "emdash",
    database: "emdash",
    password: process.env.PGPASSWORD,
  };
}

const exact = (migrations) =>
  !migrations.pending.length &&
  !migrations.unknownApplied.length &&
  JSON.stringify(migrations.knownApplied) === JSON.stringify(MIGRATION_NAMES);

async function withCmsDatabase(work) {
  const database = new Kysely({
    dialect: createDialect({ ...cmsCredentials(), pool: { min: 0, max: 1 } }),
  });
  try {
    return await database
      .connection()
      .execute((connection) => work(connection));
  } finally {
    await database.destroy();
  }
}

async function provisionDatabase() {
  const coreDatabase = process.env.CORE_POSTGRES_DB;
  const coreRole = process.env.CORE_POSTGRES_USER;
  const corePassword = process.env.CORE_POSTGRES_PASSWORD;
  if (!coreDatabase || !coreRole || !corePassword)
    throw new Refused("core_operator_credentials_required");
  const { host, password } = cmsCredentials();
  const admin = new pg.Pool({
    host,
    database: coreDatabase,
    user: coreRole,
    password: corePassword,
    max: 1,
    connectionTimeoutMillis: 5000,
  });
  try {
    await provisionPostgres({ admin, coreDatabase, coreRole, password });
  } finally {
    await admin.end();
  }
  const migrated = await withCmsDatabase(async (connection) => {
    const before = await getExactMigrationStatus(connection);
    if (exact(before)) return false;
    // Initialize an empty database, or finish an interrupted first run: a
    // gapless prefix of this release's migrations, nothing unknown, and no
    // setup grant ever written (no editor has used this database yet).
    const prefix =
      !before.unknownApplied.length &&
      JSON.stringify(before.knownApplied) ===
        JSON.stringify(MIGRATION_NAMES.slice(0, before.knownApplied.length));
    if (
      !prefix ||
      (before.knownApplied.length &&
        (await inspectBootstrap(bootstrapDirectory)).status !== "none")
    )
      throw new Refused("upstream_migration_inventory_mismatch");
    await runMigrations(connection);
    if (!exact(await getExactMigrationStatus(connection)))
      throw new Refused("upstream_migration_inventory_mismatch");
    return true;
  });
  const pool = new pg.Pool({
    ...cmsCredentials(),
    max: 1,
    connectionTimeoutMillis: 5000,
  });
  try {
    await installIdentityMapping(pool);
  } finally {
    await pool.end();
  }
  console.log(
    `cms-provision: database ready (${migrated ? "EmDash migrations applied" : "already migrated"}; role, grants and identity mapping verified)`,
  );
}

async function arm(actor) {
  if (!uuid.test(actor ?? "")) throw new Refused("system_admin_uuid_required");
  const state = await inspectBootstrap(bootstrapDirectory);
  if (state.status === "none") await armBootstrap(bootstrapDirectory, actor);
  else if (state.status === "expired")
    await rearmExpiredBootstrap(bootstrapDirectory, actor);
  else if (state.status === "armed" && state.actor === actor) {
    console.log("cms-provision: setup grant still armed for this System Admin");
    return;
  } else if (state.status === "complete") {
    console.log("cms-provision: setup already complete; nothing armed");
    return;
  } else throw new Refused(`bootstrap_${state.status}`);
  console.log(
    "cms-provision: setup grant armed for the designated System Admin for 15 minutes",
  );
}

// Each probe reports its own state; one failing probe never hides the others.
async function status() {
  const result = {
    database: "missing",
    storage: "missing",
    bootstrap: "invalid",
    setup: "pending",
    schema: "missing",
    traffic: "closed",
  };
  try {
    await withCmsDatabase(async (connection) => {
      const migrations = await getExactMigrationStatus(connection);
      const mapping =
        await sql`SELECT to_regclass('public.leonaid_external_identity') IS NOT NULL AS present`.execute(
          connection,
        );
      // Not yet migrated (or interrupted): the database step runs again.
      // Anything else that differs from this release is refused.
      if (!exact(migrations)) {
        result.database =
          migrations.unknownApplied.length ||
          JSON.stringify(migrations.knownApplied) !==
            JSON.stringify(
              MIGRATION_NAMES.slice(0, migrations.knownApplied.length),
            )
            ? "refused"
            : "missing";
        return;
      }
      result.database = mapping.rows[0]?.present ? "ready" : "missing";
      if (result.database !== "ready") return;
      const setup = await connection
        .selectFrom("options")
        .select("value")
        .where("name", "=", "emdash:setup_complete")
        .executeTakeFirst();
      try {
        if (setup && JSON.parse(setup.value) === true)
          result.setup = "complete";
      } catch {
        result.setup = "pending";
      }
      const version = await connection
        .selectFrom("options")
        .select("value")
        .where("name", "=", "leonaid:campaign_schema_version")
        .executeTakeFirst();
      if (!version) return;
      try {
        await requireCampaignSchema(connection);
        await requireCampaignBindings(connection);
        await requireCampaignMedia(connection);
        result.schema = "ready";
      } catch {
        result.schema = "refused";
      }
    });
  } catch (error) {
    // 28P01 wrong password, 28000 unknown role, 3D000 unknown database: the
    // database step has not run (or ran with another password). Anything else
    // (server down, timeout) must not look like a step to repeat.
    if (!["28P01", "28000", "3D000"].includes(error?.code))
      result.database = "unavailable";
  }
  try {
    await createStorage({}).list({ limit: 1 });
    result.storage = "ready";
  } catch (error) {
    // RustFS answered with a client error (no bucket, unknown or refused
    // key): the storage step has not run. No answer at all is an outage.
    const status = error?.cause?.$metadata?.httpStatusCode;
    result.storage =
      Number.isInteger(status) && status >= 400 && status < 500
        ? "missing"
        : "unavailable";
  }
  try {
    result.bootstrap = (await inspectBootstrap(bootstrapDirectory)).status;
  } catch {
    result.bootstrap = "invalid";
  }
  result.traffic = (await cmsMaintenanceClosed()) ? "closed" : "open";
  for (const [key, value] of Object.entries(result))
    console.log(`${key}=${value}`);
}

const mode = process.argv[2];
try {
  if (mode === "database" && process.argv.length === 3)
    await provisionDatabase();
  else if (mode === "arm" && process.argv.length === 4)
    await arm(process.argv[3]);
  else if (mode === "status" && process.argv.length === 3) await status();
  else throw new Refused("invalid_arguments");
} catch (error) {
  // SQL and S3 errors can carry credentials or deployment identifiers.
  const reason = error instanceof Refused ? error.message : "operation_failed";
  console.error(`cms-provision: refused (${reason}); nothing was reopened`);
  process.exitCode = 1;
}
