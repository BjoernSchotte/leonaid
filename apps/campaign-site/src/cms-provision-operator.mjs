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
  resetConsumedBootstrap,
} from "./bootstrap-control.mjs";
import { campaignSchemaVersion } from "./campaign-schema.mjs";
import { requireCampaignSchema } from "./install-campaign-schema.mjs";
import { requireCampaignBindings } from "./auth/campaign-bindings.mjs";
import { requireCampaignMedia } from "./auth/campaign-media.mjs";
import { cmsMaintenanceClosed } from "./cms-maintenance.mjs";
import {
  databaseErrorState,
  migrationState,
  releaseDatabaseState,
  schemaState,
  storageErrorState,
} from "./cms-provision-state.mjs";

// Image-owned production provisioning operator (./leonaid pilot-cms-provision,
// specs/multi-domain R11). It never starts HTTP, never prints credentials or
// SQL errors, and every mode is safe to repeat:
//   database     role, database and grants (operator credentials), then the
//                upstream EmDash migrations of an empty database and the
//                identity mapping (CMS credentials). An existing database must
//                already carry this release's migrations (or a gapless prefix
//                of an interrupted first run): upgrades belong to the reviewed
//                migration controller, never to provisioning.
//   arm UUID     one-time setup grant for the designated Core System Admin.
//   reset-setup  withdraw a consumed grant whose setup never completed, only
//                while the CMS holds nothing but LeonAid's identity mapping.
//   status       read-only state of every step, one "key=value" line each;
//                database=pending: a live CMS waits for this image's EmDash
//                migrations (pilot-release applies them).
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

async function option(connection, name) {
  const row = await connection
    .selectFrom("options")
    .select("value")
    .where("name", "=", name)
    .executeTakeFirst();
  return row?.value;
}

async function setupComplete(connection) {
  try {
    const value = await option(connection, "emdash:setup_complete");
    return value !== undefined && JSON.parse(value) === true;
  } catch {
    return false;
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
    const state = migrationState(before, MIGRATION_NAMES);
    if (state === "ready") return false;
    // Initialize an empty database, or finish an interrupted first run while
    // no setup grant was ever written (no editor has used this database).
    if (
      state === "refused" ||
      (before.knownApplied.length &&
        (await inspectBootstrap(bootstrapDirectory)).status !== "none")
    )
      throw new Refused("upstream_migration_inventory_mismatch");
    await runMigrations(connection);
    if (
      migrationState(
        await getExactMigrationStatus(connection),
        MIGRATION_NAMES,
      ) !== "ready"
    )
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

const until = (expiresAt) => new Date(expiresAt).toISOString();

async function arm(actor) {
  if (!uuid.test(actor ?? "")) throw new Refused("system_admin_uuid_required");
  const state = await inspectBootstrap(bootstrapDirectory);
  if (state.status === "none") await armBootstrap(bootstrapDirectory, actor);
  else if (state.status === "expired")
    await rearmExpiredBootstrap(bootstrapDirectory, actor);
  else if (state.status === "armed" && state.actor === actor) {
    console.log(
      `cms-provision: setup grant still armed for this System Admin until ${until(state.expiresAt)}`,
    );
    return;
  } else if (state.status === "armed")
    // One grant at a time: another address never silently replaces it.
    throw new Refused(
      `setup_armed_for_another_system_admin_until_${until(state.expiresAt)}`,
    );
  else if (state.status === "complete") {
    console.log("cms-provision: setup already complete; nothing armed");
    return;
  } else throw new Refused(`bootstrap_${state.status}`);
  const armed = await inspectBootstrap(bootstrapDirectory);
  console.log(
    `cms-provision: setup grant armed for the designated System Admin until ${until(armed.expiresAt)}`,
  );
}

// A consumed grant whose setup never completed may be withdrawn only while
// the CMS still holds nothing an editor made: exact EmDash inventory, no
// completed setup, no campaign schema, no media or revisions, and only users
// that LeonAid's own identity mapping created (the sign-in of the System
// Admin creates one before the setup). Prints the withdrawn actor for the
// audit record ./leonaid writes into Core.
async function resetSetup() {
  const state = await inspectBootstrap(bootstrapDirectory);
  if (state.status !== "consumed")
    throw new Refused(`bootstrap_${state.status}`);
  await withCmsDatabase(async (connection) => {
    if (
      migrationState(
        await getExactMigrationStatus(connection),
        MIGRATION_NAMES,
      ) !== "ready"
    )
      throw new Refused("upstream_migration_inventory_mismatch");
    if (await setupComplete(connection)) throw new Refused("setup_complete");
    if (
      (await option(connection, "leonaid:campaign_schema_version")) !==
      undefined
    )
      throw new Refused("campaign_schema_present");
    const used = await sql`SELECT
        (SELECT count(*) FROM public.media) AS media,
        (SELECT count(*) FROM public.revisions) AS revisions,
        (SELECT count(*) FROM public.users u WHERE NOT EXISTS (
          SELECT 1 FROM public.leonaid_external_identity i
          WHERE i.cms_user_id = u.id)) AS local_users`.execute(connection);
    const row = used.rows[0];
    if (Number(row.media) || Number(row.revisions) || Number(row.local_users))
      throw new Refused("cms_already_used");
  });
  const previous = await resetConsumedBootstrap(bootstrapDirectory);
  console.log(`cms-provision: setup grant withdrawn; actor=${previous}`);
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
  let grant = null;
  try {
    grant = await inspectBootstrap(bootstrapDirectory);
    result.bootstrap = grant.status;
  } catch {
    result.bootstrap = "invalid";
  }
  try {
    await withCmsDatabase(async (connection) => {
      const migrations = await getExactMigrationStatus(connection);
      result.database = releaseDatabaseState(
        migrationState(migrations, MIGRATION_NAMES),
        migrations.knownApplied.length,
        result.bootstrap,
      );
      if (result.database === "pending") {
        // This image's schema registry may read columns that only its own
        // migrations add: the campaign schema is checked after them.
        if (await setupComplete(connection)) result.setup = "complete";
        result.schema = "pending";
        return;
      }
      const mapping =
        await sql`SELECT to_regclass('public.leonaid_external_identity') IS NOT NULL AS present`.execute(
          connection,
        );
      if (result.database === "ready" && !mapping.rows[0]?.present)
        result.database = "missing";
      if (result.database !== "ready") return;
      if (await setupComplete(connection)) result.setup = "complete";
      const versions = {
        schema: await option(connection, "leonaid:campaign_schema_version"),
        bindings: await option(connection, "leonaid:campaign_binding_version"),
        media: await option(connection, "leonaid:campaign_media_version"),
      };
      const verified = {};
      for (const [part, check] of [
        ["schema", requireCampaignSchema],
        ["bindings", requireCampaignBindings],
        ["media", requireCampaignMedia],
      ]) {
        if (versions[part] === undefined) continue;
        try {
          await check(connection);
          verified[part] = true;
        } catch {
          verified[part] = false;
        }
      }
      result.schema = schemaState(
        versions,
        {
          schema: JSON.stringify(campaignSchemaVersion),
          bindings: "2",
          media: "1",
        },
        verified,
      );
    });
  } catch (error) {
    result.database = databaseErrorState(error);
  }
  try {
    await createStorage({}).list({ limit: 1 });
    result.storage = "ready";
  } catch (error) {
    result.storage = storageErrorState(error);
  }
  result.traffic = (await cmsMaintenanceClosed()) ? "closed" : "open";
  for (const [key, value] of Object.entries(result))
    console.log(`${key}=${value}`);
  if (grant?.status === "armed") {
    console.log(`grant_actor=${grant.actor}`);
    console.log(`grant_until=${until(grant.expiresAt)}`);
  }
}

const mode = process.argv[2];
try {
  if (mode === "database" && process.argv.length === 3)
    await provisionDatabase();
  else if (mode === "arm" && process.argv.length === 4)
    await arm(process.argv[3]);
  else if (mode === "reset-setup" && process.argv.length === 3)
    await resetSetup();
  else if (mode === "status" && process.argv.length === 3) await status();
  else throw new Refused("invalid_arguments");
} catch (error) {
  // SQL and S3 errors can carry credentials or deployment identifiers.
  const reason = error instanceof Refused ? error.message : "operation_failed";
  console.error(`cms-provision: refused (${reason}); nothing was reopened`);
  process.exitCode = 1;
}
