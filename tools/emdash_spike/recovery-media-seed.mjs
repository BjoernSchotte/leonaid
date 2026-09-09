// Explicit fixture setup on the source only, never on a restore target.
import assert from "node:assert/strict";
import { Kysely } from "kysely";
import { createDialect } from "emdash/db/postgres";
import { installCampaignMedia } from "../../apps/campaign-site/src/auth/campaign-media.mjs";

assert.equal(process.env.PGHOST, "core-postgres");
const database = new Kysely({
  dialect: createDialect({
    host: "core-postgres",
    user: "emdash",
    database: "emdash",
    password: process.env.CMS_POSTGRES_PASSWORD,
  }),
});
try {
  await installCampaignMedia(database);
  console.log(
    "recovery-sql: source media guard explicitly installed before backup",
  );
} finally {
  await database.destroy();
}
