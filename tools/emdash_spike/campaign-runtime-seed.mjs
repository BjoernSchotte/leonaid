import assert from "node:assert/strict";
import { Kysely } from "kysely";
import { createDialect } from "emdash/db/postgres";
import { applySeed } from "emdash/seed";
import { ContentRepository, handleContentList } from "emdash";
import { installCampaignBindings } from "../../apps/campaign-site/src/auth/campaign-bindings.mjs";
import { installCampaignSchema } from "../../apps/campaign-site/src/install-campaign-schema.mjs";

const database = new Kysely({
  dialect: createDialect({
    host: process.env.PGHOST,
    user: "emdash",
    database: "emdash",
    password: process.env.CMS_POSTGRES_PASSWORD,
  }),
});
try {
  const actions = process.argv.includes("--isolation") ? [1, 2, 3] : [1, 2];
  await installCampaignSchema(database);
  const result = await applySeed(
    database,
    {
      version: "1",
      content: {
        campaign_pages: actions.map((action, index) => ({
          id: `proof-${index}`,
          slug: `proof-${index}`,
          status: "published",
          data: {
            action_id: `20000000-0000-4000-8000-00000000000${action}`,
            title: `synthetic campaign ${action} story ${index}`,
          },
        })),
      },
    },
    { includeContent: true, onConflict: "error" },
  );
  assert.equal(result.content.created, actions.length);
  await installCampaignBindings(database);
  const entries = await handleContentList(database, "campaign_pages", {});
  assert.equal(entries.success, true);
  const repository = new ContentRepository(database);
  for (const entry of entries.data.items) {
    await repository.updateDraftAware("campaign_pages", entry.id, {
      data: { title: `${entry.data.title} revised` },
    });
  }
  console.log(
    `campaign-runtime: ${actions.length} uniquely bound real synthetic entries and revisions seeded`,
  );
} finally {
  await database.destroy();
}
