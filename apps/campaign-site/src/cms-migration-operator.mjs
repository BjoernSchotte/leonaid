import { Kysely, sql } from "kysely";
import { createDialect } from "emdash/db/postgres";
import { getExactMigrationStatus, MIGRATION_NAMES } from "emdash/db";
import { closeCmsTraffic, cmsMaintenanceClosed } from "./cms-maintenance.mjs";
import {
  installCampaignSchema,
  requireCampaignSchema,
} from "./install-campaign-schema.mjs";
import { requireCampaignBindings } from "./auth/campaign-bindings.mjs";
import { requireCampaignMedia } from "./auth/campaign-media.mjs";

// Explicit image-owned operator. It never starts HTTP, provisions roles, runs
// upstream upgrades, repairs guards, imports content or reopens CMS traffic.
// The controller must stop CMS processes after closing traffic and before DDL
// to drain/terminate requests which entered before the marker was installed.
const mode = process.argv[2];
try {
  if (process.argv.length !== 3) throw new Error("invalid_arguments");
  if (mode === "close") {
    await closeCmsTraffic();
  } else {
    if (!["verify", "upgrade-v1", "upgrade-v2"].includes(mode))
      throw new Error("unsupported_migration");
    if (!(await cmsMaintenanceClosed()))
      throw new Error("cms_traffic_not_closed");
    if (process.env.PGUSER !== "emdash" || process.env.PGDATABASE !== "emdash")
      throw new Error("cms_credentials_required");
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
        await sql`SET statement_timeout = '10s'`.execute(connection);
        const lock =
          await sql`SELECT pg_try_advisory_lock(724381908) AS acquired`.execute(
            connection,
          );
        if (lock.rows[0]?.acquired !== true)
          throw new Error("cms_migration_busy");
        try {
          const migrations = await getExactMigrationStatus(connection);
          if (
            migrations.pending.length ||
            migrations.unknownApplied.length ||
            JSON.stringify(migrations.knownApplied) !==
              JSON.stringify(MIGRATION_NAMES)
          )
            throw new Error("upstream_migration_inventory_mismatch");
          // Reject unrelated drift BEFORE applying editorial DDL.
          await requireCampaignBindings(connection);
          await requireCampaignMedia(connection);
          if (mode !== "verify")
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
