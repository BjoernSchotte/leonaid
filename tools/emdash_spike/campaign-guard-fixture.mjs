import { Kysely, sql } from "kysely";
import { createDialect } from "emdash/db/postgres";
import { requireCampaignBindings } from "../../apps/campaign-site/src/auth/campaign-bindings.mjs";

// Invoked only by the unique-project live proof's operator container.
const database = new Kysely({
  dialect: createDialect({
    host: process.env.PGHOST,
    user: "emdash",
    database: "emdash",
    password: process.env.CMS_POSTGRES_PASSWORD,
  }),
});
try {
  if (process.argv[2] === "disable") {
    await requireCampaignBindings(database);
    await sql`ALTER TABLE public.ec_campaign_pages DISABLE TRIGGER leonaid_campaign_binding`.execute(
      database,
    );
  } else if (process.argv[2] === "restore") {
    await sql`ALTER TABLE public.ec_campaign_pages ENABLE TRIGGER leonaid_campaign_binding`.execute(
      database,
    );
    await requireCampaignBindings(database);
  } else {
    throw new Error("expected disable or restore");
  }
  console.log("campaign-guard-fixture: synthetic guard state updated");
} finally {
  await database.destroy();
}
