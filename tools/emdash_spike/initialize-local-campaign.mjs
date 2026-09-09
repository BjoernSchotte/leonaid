import assert from "node:assert/strict";
import { Kysely } from "kysely";
import { createDialect } from "emdash/db/postgres";
import { requireCompletedBootstrap } from "../../apps/campaign-site/src/bootstrap-control.mjs";
import { installCampaignSchema } from "../../apps/campaign-site/src/install-campaign-schema.mjs";
import { installCampaignBindings } from "../../apps/campaign-site/src/auth/campaign-bindings.mjs";
import { installCampaignMedia } from "../../apps/campaign-site/src/auth/campaign-media.mjs";

// Initial local integration only, not a release migration. The caller stops the
// project's CMS before invoking this operator and leaves it stopped on failure.
// No content, identities, publication state or Core records are seeded here.
assert.equal(process.env.LEONAID_ENV, "local");
assert.equal(process.argv.length, 2);
await requireCompletedBootstrap("/app/bootstrap-state");
assert.ok(process.env.CMS_POSTGRES_PASSWORD);
const database = new Kysely({
  dialect: createDialect({
    host: "core-postgres",
    database: "emdash",
    user: "emdash",
    password: process.env.CMS_POSTGRES_PASSWORD,
    pool: { min: 0, max: 1 },
  }),
});
try {
  // Existing installers reject version/guard drift; do not enable upgrades or
  // repair another deployment's schema as a side effect of local preparation.
  await installCampaignSchema(database);
  await installCampaignBindings(database);
  await installCampaignMedia(database);
  console.log(
    "local-campaign: schema, campaign bindings and media guards ready; no content seeded",
  );
} finally {
  await database.destroy();
}
