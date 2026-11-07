import { Kysely, sql } from "kysely";
import { createDialect } from "emdash/db/postgres";
import {
  getExactMigrationStatus,
  MIGRATION_NAMES,
  runMigrations,
} from "emdash/db";
import { closeCmsTraffic, cmsMaintenanceClosed } from "./cms-maintenance.mjs";
import {
  installCampaignSchema,
  requireCampaignSchema,
} from "./install-campaign-schema.mjs";
import {
  installCampaignBindings,
  requireCampaignBindings,
} from "./auth/campaign-bindings.mjs";
import { campaignSchemaVersion } from "./campaign-schema.mjs";
import {
  installCampaignMedia,
  requireCampaignMedia,
} from "./auth/campaign-media.mjs";
import { requireCompletedBootstrap } from "./bootstrap-control.mjs";

// Explicit image-owned operator. It never starts HTTP, provisions roles, runs
// upstream upgrades, repairs guards, imports content or reopens CMS traffic.
// The controller must stop CMS processes after closing traffic and before DDL
// to drain/terminate requests which entered before the marker was installed.
// "install" is the production first install (pilot-cms-provision): after the
// designated System Admin completed the EmDash setup, it creates the campaign
// collection, binding and media guards. Each installer verifies an existing
// installation instead of repairing it, so a repeat or resumed run is a no-op.
const mode = process.argv[2];
try {
  if (process.argv.length !== 3) throw new Error("invalid_arguments");
  if (mode === "close") {
    await closeCmsTraffic();
  } else {
    if (
      ![
        "install",
        "verify",
        "upgrade-v1",
        "upgrade-v2",
        "upgrade-emdash",
      ].includes(mode)
    )
      throw new Error("unsupported_migration");
    if (!(await cmsMaintenanceClosed()))
      throw new Error("cms_traffic_not_closed");
    if (process.env.PGUSER !== "emdash" || process.env.PGDATABASE !== "emdash")
      throw new Error("cms_credentials_required");
    // The setup creates the first CMS user; installing editorial schema
    // before it would let an unconsumed setup run against a prepared schema.
    if (mode === "install")
      await requireCompletedBootstrap("/app/bootstrap-state");
    const database = new Kysely({
      dialect: createDialect({
        host: process.env.PGHOST,
        user: "emdash",
        database: "emdash",
        password: process.env.PGPASSWORD,
        pool: { min: 0, max: 1 },
      }),
    });
    try {
      // Pin one connection for the session lock across the installer's own
      // transaction. Process death releases the lock, but not the traffic gate.
      await database.connection().execute(async (connection) => {
        // Upstream data migrations (EmDash 1.x datetime normalisation) touch
        // every content row and revision; allow them more than editorial DDL.
        if (mode === "upgrade-emdash")
          await sql`SET statement_timeout = '300s'`.execute(connection);
        else await sql`SET statement_timeout = '10s'`.execute(connection);
        const lock =
          await sql`SELECT pg_try_advisory_lock(724381908) AS acquired`.execute(
            connection,
          );
        if (lock.rows[0]?.acquired !== true)
          throw new Error("cms_migration_busy");
        try {
          const exactInventory = (migrations) =>
            !migrations.pending.length &&
            !migrations.unknownApplied.length &&
            JSON.stringify(migrations.knownApplied) ===
              JSON.stringify(MIGRATION_NAMES);
          let migrations = await getExactMigrationStatus(connection);
          if (mode === "upgrade-emdash") {
            // Only an existing install of an older EmDash release: a gapless
            // prefix of this release's migrations and nothing unknown. Never
            // initialize an empty database or skip a migration here.
            const applied = migrations.knownApplied;
            if (
              !applied.length ||
              migrations.unknownApplied.length ||
              JSON.stringify(applied) !==
                JSON.stringify(MIGRATION_NAMES.slice(0, applied.length))
            )
              throw new Error("upstream_migration_inventory_mismatch");
            // Reject unrelated drift BEFORE upstream DDL and data changes. The
            // editorial schema must already be current (upgrade-v1/v2 run
            // under the previous image); the 1.x schema registry reads columns
            // that exist only after the upstream migrations, so the complete
            // collection contract is checked afterwards.
            await requireCampaignBindings(connection);
            await requireCampaignMedia(connection);
            const editorial = await connection
              .selectFrom("options")
              .select("value")
              .where("name", "=", "leonaid:campaign_schema_version")
              .executeTakeFirst();
            if (editorial?.value !== JSON.stringify(campaignSchemaVersion))
              throw new Error("campaign_schema_version_mismatch");
            // EmDash's own migrator, with its own PostgreSQL migration lock,
            // on this pinned session. A failed migration stops the upgrade;
            // the recovery point taken before it is the rollback.
            await runMigrations(connection);
            migrations = await getExactMigrationStatus(connection);
          }
          if (!exactInventory(migrations))
            throw new Error("upstream_migration_inventory_mismatch");
          if (mode === "install") {
            const setup = await connection
              .selectFrom("options")
              .select("value")
              .where("name", "=", "emdash:setup_complete")
              .executeTakeFirst();
            // Same reading as setupIsComplete() in database-ready.ts.
            if (!setup || JSON.parse(setup.value) !== true)
              throw new Error("cms_setup_pending");
            await installCampaignSchema(connection);
            await installCampaignBindings(connection);
            await installCampaignMedia(connection);
          }
          // Reject unrelated drift BEFORE applying editorial DDL.
          await requireCampaignBindings(connection);
          await requireCampaignMedia(connection);
          if (mode === "upgrade-v1" || mode === "upgrade-v2")
            await installCampaignSchema(connection, {
              upgradeFromVersion1: mode === "upgrade-v1",
              upgradeFromVersion2: mode === "upgrade-v2",
            });
          await requireCampaignSchema(connection);
        } finally {
          await sql`SELECT pg_advisory_unlock(724381908)`.execute(connection);
        }
      });
    } finally {
      await database.destroy();
    }
  }
  console.log(`cms-migration: ${mode} passed; CMS traffic remains closed`);
} catch {
  console.error("cms-migration: refused; CMS traffic must remain closed");
  process.exitCode = 1;
}
