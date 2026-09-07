import pg from "pg";
import { Kysely, sql } from "kysely";
import { createDialect } from "emdash/db/postgres";
import { getExactMigrationStatus, MIGRATION_NAMES } from "emdash/db";
import { provisionPostgres } from "../emdash_spike/provision-postgres.mjs";
import { requireCampaignBindings } from "../../apps/campaign-site/src/auth/campaign-bindings.mjs";
import { requireCampaignSchema } from "../../apps/campaign-site/src/install-campaign-schema.mjs";
import { requireCampaignMedia } from "../../apps/campaign-site/src/auth/campaign-media.mjs";

// Explicit one-shot operator, never the CMS HTTP process. Provisioning does
// not run CMS migrations or repair missing guards in restored SQL.
const mode = process.argv[2];
try {
  if (mode === "provision") {
    const admin = new pg.Pool({ connectionTimeoutMillis: 5000 });
    try {
      await provisionPostgres({
        admin,
        coreDatabase: process.env.PGDATABASE,
        coreRole: process.env.PGUSER,
        password: process.env.CMS_POSTGRES_PASSWORD,
      });
    } finally {
      await admin.end();
    }
  } else if (mode === "verify" || mode === "verify-application") {
    const database = new Kysely({
      dialect: createDialect({
        host: process.env.PGHOST,
        database: "emdash",
        user: "emdash",
        password: process.env.CMS_POSTGRES_PASSWORD,
      }),
    });
    try {
      await database
        .transaction()
        .setIsolationLevel("repeatable read")
        .execute(async (transaction) => {
          await sql`SET TRANSACTION READ ONLY`.execute(transaction);
          await sql`SET LOCAL statement_timeout = '5s'`.execute(transaction);
          await requireCampaignBindings(transaction);
          if (mode === "verify-application") {
            const migrations = await getExactMigrationStatus(transaction);
            if (
              migrations.pending.length ||
              migrations.unknownApplied.length ||
              JSON.stringify(migrations.knownApplied) !==
                JSON.stringify(MIGRATION_NAMES)
            )
              throw new Error("cms_migration_inventory_mismatch");
            await requireCampaignSchema(transaction);
            await requireCampaignMedia(transaction);
          }
        });
    } finally {
      await database.destroy();
    }
    const forbidden = new pg.Client({
      host: process.env.PGHOST,
      database: process.env.PGDATABASE,
      user: "emdash",
      password: process.env.CMS_POSTGRES_PASSWORD,
      connectionTimeoutMillis: 5000,
    });
    try {
      let denied = false;
      try {
        await forbidden.connect();
      } catch (error) {
        if (error.code === "42501") denied = true;
        else throw error;
      }
      if (!denied) throw new Error("cross_database_access");
    } finally {
      await forbidden.end();
    }
  } else {
    throw new Error("unknown_recovery_operation");
  }
  console.log(
    `cms-recovery: ${mode} passed; no HTTP startup or implicit migration`,
  );
} catch {
  console.error("cms-recovery: refused; CMS must remain stopped");
  process.exitCode = 1;
}
