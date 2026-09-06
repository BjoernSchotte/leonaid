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
  } else if (process.argv[2] === "fail-attribution") {
    await sql`CREATE FUNCTION public.synthetic_reject_attribution() RETURNS trigger
      LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic late write failure'; END $$`.execute(
      database,
    );
    await sql`CREATE TRIGGER synthetic_reject_attribution BEFORE UPDATE OF author_id
      ON public.revisions FOR EACH ROW EXECUTE FUNCTION public.synthetic_reject_attribution()`.execute(
      database,
    );
  } else if (process.argv[2] === "restore-attribution") {
    await sql`DROP TRIGGER synthetic_reject_attribution ON public.revisions`.execute(
      database,
    );
    await sql`DROP FUNCTION public.synthetic_reject_attribution()`.execute(
      database,
    );
  } else if (process.argv[2] === "fail-discard") {
    await sql`CREATE FUNCTION public.synthetic_reject_discard() RETURNS trigger
      LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic commit failure'; END $$`.execute(
      database,
    );
    await sql`CREATE CONSTRAINT TRIGGER synthetic_reject_discard AFTER UPDATE
      ON public.ec_campaign_pages DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      WHEN (OLD.draft_revision_id IS NOT NULL AND NEW.draft_revision_id IS NULL)
      EXECUTE FUNCTION public.synthetic_reject_discard()`.execute(database);
  } else if (process.argv[2] === "restore-discard") {
    await sql`DROP TRIGGER synthetic_reject_discard ON public.ec_campaign_pages`.execute(
      database,
    );
    await sql`DROP FUNCTION public.synthetic_reject_discard()`.execute(
      database,
    );
  } else if (process.argv[2] === "fail-unpublish") {
    await sql`CREATE FUNCTION public.synthetic_reject_unpublish() RETURNS trigger
      LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic unpublish commit failure'; END $$`.execute(
      database,
    );
    await sql`CREATE CONSTRAINT TRIGGER synthetic_reject_unpublish AFTER UPDATE
      ON public.ec_campaign_pages DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      WHEN (OLD.status='published' AND NEW.status='draft')
      EXECUTE FUNCTION public.synthetic_reject_unpublish()`.execute(database);
  } else if (process.argv[2] === "restore-unpublish") {
    await sql`DROP TRIGGER synthetic_reject_unpublish ON public.ec_campaign_pages`.execute(
      database,
    );
    await sql`DROP FUNCTION public.synthetic_reject_unpublish()`.execute(
      database,
    );
  } else {
    throw new Error("unknown synthetic fixture operation");
  }
  console.log("campaign-guard-fixture: synthetic guard state updated");
} finally {
  await database.destroy();
}
