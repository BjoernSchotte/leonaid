import assert from "node:assert/strict";
import { Kysely, sql } from "kysely";
import { createDialect } from "emdash/db/postgres";
import { ContentRepository } from "emdash";
import { applySeed } from "emdash/seed";
import { campaignCollectionV2 } from "../../apps/campaign-site/src/campaign-schema.mjs";
import { installCampaignBindings } from "../../apps/campaign-site/src/auth/campaign-bindings.mjs";
import { installCampaignMedia } from "../../apps/campaign-site/src/auth/campaign-media.mjs";

const database = new Kysely({
  dialect: createDialect({
    host: process.env.PGHOST,
    user: "emdash",
    database: "emdash",
    password: process.env.CMS_POSTGRES_PASSWORD,
  }),
});
const snapshot = async () => ({
  content: (
    await sql`SELECT to_jsonb(p) - ARRAY['brand_logo','story_eyebrow','story_title'] AS row FROM ec_campaign_pages p ORDER BY id`.execute(
      database,
    )
  ).rows,
  revisions: (await sql`SELECT * FROM revisions ORDER BY id`.execute(database))
    .rows,
});
try {
  const mode = process.argv[2];
  if (mode === "prepare") {
    await applySeed(
      database,
      { version: "1", collections: [campaignCollectionV2] },
      { includeContent: false, onConflict: "error" },
    );
    await database
      .insertInto("options")
      .values({ name: "leonaid:campaign_schema_version", value: "2" })
      .execute();
    await installCampaignBindings(database);
    await installCampaignMedia(database);
    const repository = new ContentRepository(database);
    const item = await repository.create({
      type: "campaign_pages",
      slug: "synthetic-operator",
      status: "published",
      data: {
        action_id: "20000000-0000-4000-8000-000000000001",
        title: "Retain published content",
      },
    });
    await repository.updateDraftAware("campaign_pages", item.id, {
      data: { title: "Retain draft content" },
    });
    await database
      .insertInto("options")
      .values({
        name: "synthetic:migration-snapshot",
        value: JSON.stringify(await snapshot()),
      })
      .execute();
    await sql`CREATE FUNCTION public.synthetic_operator_failure() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic_operator_failure'; END; $$`.execute(
      database,
    );
    await sql`CREATE TRIGGER synthetic_operator_failure BEFORE INSERT ON public._emdash_fields FOR EACH ROW WHEN (NEW.slug='story_eyebrow') EXECUTE FUNCTION public.synthetic_operator_failure()`.execute(
      database,
    );
  } else if (mode === "clear-failure") {
    await sql`DROP TRIGGER synthetic_operator_failure ON public._emdash_fields`.execute(
      database,
    );
    await sql`DROP FUNCTION public.synthetic_operator_failure()`.execute(
      database,
    );
  } else if (mode === "hold-lock") {
    await database.connection().execute(async (connection) => {
      await sql`SELECT pg_advisory_lock(724381908)`.execute(connection);
      console.log("migration-fixture: exclusive lock held");
      await new Promise(() => {});
    });
  } else if (mode === "assert-lock") {
    await database.connection().execute(async (connection) => {
      const result =
        await sql`SELECT pg_try_advisory_lock(724381908) AS acquired`.execute(
          connection,
        );
      if (result.rows[0].acquired) {
        await sql`SELECT pg_advisory_unlock(724381908)`.execute(connection);
        throw new Error("lock_not_held");
      }
    });
  } else if (["assert-v2", "assert-v3"].includes(mode)) {
    const row = await database
      .selectFrom("options")
      .select("value")
      .where("name", "=", "leonaid:campaign_schema_version")
      .executeTakeFirstOrThrow();
    assert.equal(row.value, mode === "assert-v2" ? "2" : "3");
    const saved = await database
      .selectFrom("options")
      .select("value")
      .where("name", "=", "synthetic:migration-snapshot")
      .executeTakeFirstOrThrow();
    assert.deepEqual(
      JSON.parse(JSON.stringify(await snapshot())),
      JSON.parse(saved.value),
    );
    const columns = (
      await sql`SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='ec_campaign_pages' AND column_name IN ('brand_logo','story_eyebrow','story_title')`.execute(
        database,
      )
    ).rows;
    assert.equal(columns.length, mode === "assert-v2" ? 0 : 3);
  } else throw new Error("unsupported_fixture");
  console.log(`migration-fixture: ${mode} passed`);
} finally {
  await database.destroy();
}
