import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import pg from "pg";
import { Kysely, sql } from "kysely";
import { createDialect } from "emdash/db/postgres";
import { runMigrations } from "emdash/db";
import { ContentRepository, SchemaRegistry } from "emdash";
import { validateSeed } from "emdash/seed";
import { provisionPostgres } from "./provision-postgres.mjs";
import { installCampaignSchema } from "../../apps/campaign-site/src/install-campaign-schema.mjs";
import { exportCampaignSchema } from "../../apps/campaign-site/src/campaign-schema.mjs";
import { readFile } from "node:fs/promises";
import { generateCampaignTypes } from "./campaign-typegen.mjs";
import "./campaign-types-proof.mjs";

const exported = exportCampaignSchema();
assert.equal(exported, exportCampaignSchema());
const contract = JSON.parse(exported);
assert.deepEqual(Object.keys(contract), ["schema_version", "seed"]);
assert.equal(contract.schema_version, 2);
assert.deepEqual(Object.keys(contract.seed), ["version", "collections"]);
assert.equal(validateSeed(contract.seed).valid, true);

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
  const results = await Promise.all(
    Array.from({ length: 3 }, () => installCampaignSchema(database)),
  );
  assert.equal(results.filter((result) => result.created).length, 1);
  const registry = new SchemaRegistry(database);
  const schema = await registry.getCollectionWithFields("campaign_pages");
  const types = await generateCampaignTypes(schema);
  assert.equal(types, await generateCampaignTypes());
  assert.equal(
    types,
    await generateCampaignTypes({
      ...schema,
      fields: [...schema.fields].reverse(),
    }),
  );
  assert.equal(
    types,
    await readFile(
      new URL(
        "../../apps/campaign-site/src/campaign-fields.generated.ts",
        import.meta.url,
      ),
      "utf8",
    ),
  );
  assert.equal(
    schema.fields.length,
    contract.seed.collections[0].fields.length,
  );
  const repository = new ContentRepository(database);
  await repository.create({
    type: "campaign_pages",
    slug: "synthetic-schema-preservation",
    status: "draft",
    data: {
      action_id: "20000000-0000-4000-8000-000000000001",
      title: "Preserve editorial content",
      hero_title: "Preserve hero",
    },
  });
  const content = async () =>
    (
      await sql`SELECT * FROM public.ec_campaign_pages ORDER BY id`.execute(
        database,
      )
    ).rows;
  const before = await content();
  assert.equal(before.length, 1);
  const versions = await database
    .selectFrom("options")
    .selectAll()
    .where("name", "=", "leonaid:campaign_schema_version")
    .execute();
  assert.equal((await installCampaignSchema(database)).created, false);
  assert.deepEqual(await content(), before);
  assert.deepEqual(
    await registry.getCollectionWithFields("campaign_pages"),
    schema,
  );
  assert.deepEqual(
    await database
      .selectFrom("options")
      .selectAll()
      .where("name", "=", "leonaid:campaign_schema_version")
      .execute(),
    versions,
  );
  await registry.updateField("campaign_pages", "hero_title", {
    validation: { maxLength: 9999 },
  });
  await assert.rejects(
    installCampaignSchema(database),
    /campaign_schema_drift/,
  );
  assert.equal(
    (await registry.getField("campaign_pages", "hero_title")).validation
      .maxLength,
    9999,
  );
  assert.deepEqual(await content(), before);
  await registry.updateField("campaign_pages", "hero_title", {
    validation: { maxLength: 180 },
  });
  await installCampaignSchema(database);
  await database
    .updateTable("options")
    .set({ value: "999" })
    .where("name", "=", "leonaid:campaign_schema_version")
    .execute();
  await assert.rejects(
    installCampaignSchema(database),
    /campaign_schema_version_mismatch/,
  );
  assert.deepEqual(await content(), before);
  assert.equal(
    (
      await database
        .selectFrom("options")
        .select("value")
        .where("name", "=", "leonaid:campaign_schema_version")
        .executeTakeFirstOrThrow()
    ).value,
    "999",
  );
  console.log(
    "schema-runtime: OK: deterministic content-free seed export, compiled generated types match installed schema, real PostgreSQL concurrent installation, repeatability without content/schema writes, explicit schema/version drift denial",
  );
} finally {
  await database.destroy();
}
