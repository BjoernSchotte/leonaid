import { Kysely } from "kysely";
import { createDialect } from "emdash/db/postgres";
import { ContentRepository } from "emdash";
import { requireCampaignBindings } from "../../apps/campaign-site/src/auth/campaign-bindings.mjs";

// Additional synthetic campaigns, after the standard four-entry regression.
// Keep Core's real lifecycle guards: never reactivate an archived fixture.
const database = new Kysely({
  dialect: createDialect({
    host: process.env.PGHOST,
    user: "emdash",
    database: "emdash",
    password: process.env.CMS_POSTGRES_PASSWORD,
  }),
});
try {
  await requireCampaignBindings(database);
  const repository = new ContentRepository(database);
  for (const suffix of [41, 42]) {
    const entry = await repository.create({
      type: "campaign_pages",
      slug: `synthetic-publication-${suffix}`,
      data: {
        action_id: `20000000-0000-4000-8000-${String(suffix).padStart(12, "0")}`,
        title: `synthetic unpublished campaign ${suffix}`,
      },
    });
    await repository.updateDraftAware("campaign_pages", entry.id, {
      data: { title: `synthetic revised campaign ${suffix}` },
    });
  }
  console.log(
    "campaign-publication-fixture: draft and scheduled Core campaign content ready",
  );
} finally {
  await database.destroy();
}
