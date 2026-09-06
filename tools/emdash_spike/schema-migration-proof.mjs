import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import pg from "pg";
import { Kysely, sql } from "kysely";
import { createDialect } from "emdash/db/postgres";
import { runMigrations } from "emdash/db";
import { ContentRepository, SchemaRegistry } from "emdash";
import { applySeed } from "emdash/seed";
import { provisionPostgres } from "./provision-postgres.mjs";
import { installCampaignSchema } from "../../apps/campaign-site/src/install-campaign-schema.mjs";
import { campaignCollectionV1 } from "../../apps/campaign-site/src/campaign-schema.mjs";

const admin = new pg.Pool({ connectionTimeoutMillis: 3000 });
const password = randomBytes(32).toString("hex");
try {
  await provisionPostgres({
    admin,
    coreDatabase: "leonaid",
    coreRole: "leonaid",
    password,
  });
} finally {
  await admin.end();
}
const database = new Kysely({
  dialect: createDialect({
    host: process.env.PGHOST,
    user: "emdash",
    database: "emdash",
    password,
  }),
});
try {
  await runMigrations(database);
  await applySeed(
    database,
    { version: "1", collections: [campaignCollectionV1] },
    { includeContent: false, onConflict: "error" },
  );
  await database
    .insertInto("options")
    .values({ name: "leonaid:campaign_schema_version", value: "1" })
    .execute();
  const repository = new ContentRepository(database);
  const item = await repository.create({
    type: "campaign_pages",
    slug: "synthetic-v1",
    status: "published",
    data: {
      action_id: "20000000-0000-4000-8000-000000000001",
      title: "Keep published text",
      partners: [{ name: "Keep partner" }],
    },
  });
  await repository.updateDraftAware("campaign_pages", item.id, {
    data: { title: "Keep draft text" },
  });
  const registry = new SchemaRegistry(database);
  const snapshot = async () => ({
    content: (
      await sql`SELECT to_jsonb(p) - 'hero_image' - 'social_image' AS row FROM public.ec_campaign_pages p ORDER BY id`.execute(
        database,
      )
    ).rows,
    revisions: (
      await sql`SELECT * FROM public.revisions ORDER BY id`.execute(database)
    ).rows,
    fields: await registry.getCollectionWithFields("campaign_pages"),
    version: (
      await database
        .selectFrom("options")
        .select("value")
        .where("name", "=", "leonaid:campaign_schema_version")
        .executeTakeFirstOrThrow()
    ).value,
  });
  const before = await snapshot();
  await assert.rejects(
    installCampaignSchema(database),
    /campaign_schema_version_mismatch/,
  );
  assert.deepEqual(await snapshot(), before);
  await registry.updateField("campaign_pages", "hero_title", {
    validation: { maxLength: 999 },
  });
  await assert.rejects(
    installCampaignSchema(database, { upgradeFromVersion1: true }),
    /campaign_schema_drift/,
  );
  assert.equal((await snapshot()).version, "1");
  await registry.updateField("campaign_pages", "hero_title", {
    validation: { maxLength: 180 },
  });
  // A real failure on the SECOND new field must roll back the first DDL and
  // repeater metadata as well as the version marker.
  await sql`CREATE FUNCTION public.synthetic_schema_failure() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic_schema_failure'; END; $$`.execute(
    database,
  );
  await sql`CREATE TRIGGER synthetic_schema_failure BEFORE INSERT ON public._emdash_fields FOR EACH ROW WHEN (NEW.slug='social_image') EXECUTE FUNCTION public.synthetic_schema_failure()`.execute(
    database,
  );
  const preFailure = await snapshot();
  await assert.rejects(
    installCampaignSchema(database, { upgradeFromVersion1: true }),
  );
  assert.deepEqual(await snapshot(), preFailure);
  const columns = (
    await sql`SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='ec_campaign_pages' AND column_name IN ('hero_image','social_image')`.execute(
      database,
    )
  ).rows;
  assert.equal(columns.length, 0);
  await sql`DROP TRIGGER synthetic_schema_failure ON public._emdash_fields`.execute(
    database,
  );
  await sql`DROP FUNCTION public.synthetic_schema_failure()`.execute(database);
  const results = await Promise.all(
    Array.from({ length: 3 }, () =>
      installCampaignSchema(database, { upgradeFromVersion1: true }),
    ),
  );
  assert.equal(results.filter((result) => result.upgraded).length, 1);
  const after = await snapshot();
  assert.equal(after.version, "2");
  assert.deepEqual(after.content, before.content);
  assert.deepEqual(after.revisions, before.revisions);
  assert.equal(after.fields.fields.length, before.fields.fields.length + 2);
  assert.deepEqual(await installCampaignSchema(database), {
    schemaVersion: 2,
    created: false,
    upgraded: false,
  });
  assert.deepEqual(await snapshot(), after);
  console.log(
    "schema-migration: OK: explicit version-1 preflight, drift refusal, actual mid-DDL failure rollback, concurrent one-winner version-2 upgrade, published/draft/revision preservation and repeatability",
  );
} finally {
  await database.destroy();
}
