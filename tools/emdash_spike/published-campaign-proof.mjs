import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import pg from "pg";
import { Kysely, sql } from "kysely";
import { createDialect } from "emdash/db/postgres";
import { runMigrations } from "emdash/db";
import { ContentRepository } from "emdash";
import { provisionPostgres } from "./provision-postgres.mjs";
import { installCampaignSchema } from "../../apps/campaign-site/src/install-campaign-schema.mjs";
import { installCampaignBindings } from "../../apps/campaign-site/src/auth/campaign-bindings.mjs";
import {
  readPublishedCampaign,
  PublishedCampaignUnavailable,
} from "../../apps/campaign-site/src/public/published-campaign.mjs";

const password = randomBytes(32).toString("hex");
const admin = new pg.Pool({ connectionTimeoutMillis: 3000 });
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
const actionId = "20000000-0000-4000-8000-000000000001";
const foreignId = "20000000-0000-4000-8000-000000000002";
try {
  await runMigrations(database);
  await installCampaignSchema(database);
  await installCampaignBindings(database);
  const repository = new ContentRepository(database);
  const entry = await repository.create({
    type: "campaign_pages",
    slug: "cms-slug-is-not-authority",
    data: {
      action_id: actionId,
      title: "Synthetic published story",
      hero_summary: "Public summary",
    },
  });
  const read = () => readPublishedCampaign(database, actionId);
  assert.equal(await read(), null);
  await repository.publish("campaign_pages", entry.id);
  const live = await read();
  assert.deepEqual(live, { entryId: entry.id, data: entry.data });
  await repository.updateDraftAware("campaign_pages", entry.id, {
    data: { title: "PRIVATE_DRAFT_CANARY", hero_summary: "Private follow-up" },
  });
  assert.deepEqual(await read(), live);
  assert.equal(await readPublishedCampaign(database, foreignId), null);
  const foreign = await repository.create({
    type: "campaign_pages",
    slug: "different-campaign",
    data: { action_id: foreignId, title: "Foreign campaign story" },
  });
  await repository.publish("campaign_pages", foreign.id);
  assert.deepEqual(await readPublishedCampaign(database, foreignId), {
    entryId: foreign.id,
    data: foreign.data,
  });
  assert.deepEqual(await read(), live);
  for (const value of [entry.slug, entry.id, "' OR 1=1 --", null])
    await assert.rejects(
      () => readPublishedCampaign(database, value),
      PublishedCampaignUnavailable,
    );
  await repository.publish("campaign_pages", entry.id);
  assert.equal((await read()).data.title, "PRIVATE_DRAFT_CANARY");
  await repository.unpublish("campaign_pages", entry.id);
  assert.equal(await read(), null);
  await repository.publish("campaign_pages", entry.id);
  const restored = await read();
  for (const state of ["draft", "scheduled"]) {
    await database
      .updateTable("ec_campaign_pages")
      .set({ status: state })
      .where("id", "=", entry.id)
      .execute();
    assert.equal(await read(), null);
  }
  await database
    .updateTable("ec_campaign_pages")
    .set({ status: "published", deleted_at: new Date().toISOString() })
    .where("id", "=", entry.id)
    .execute();
  assert.equal(await read(), null);
  await database
    .updateTable("ec_campaign_pages")
    .set({ deleted_at: null })
    .where("id", "=", entry.id)
    .execute();
  assert.deepEqual(await read(), restored);
  // Simulate incompatible stored content, not a permitted editor mutation.
  await database
    .updateTable("ec_campaign_pages")
    .set({ theme: "unregistered" })
    .where("id", "=", entry.id)
    .execute();
  await assert.rejects(read, PublishedCampaignUnavailable);
  await database
    .updateTable("ec_campaign_pages")
    .set({ theme: null })
    .where("id", "=", entry.id)
    .execute();
  assert.deepEqual(await read(), restored);
  await sql`ALTER TABLE public.ec_campaign_pages DISABLE TRIGGER leonaid_campaign_binding`.execute(
    database,
  );
  await assert.rejects(read, PublishedCampaignUnavailable);
  await sql`ALTER TABLE public.ec_campaign_pages ENABLE TRIGGER leonaid_campaign_binding`.execute(
    database,
  );
  assert.deepEqual(await read(), restored);
  const blocker = new pg.Client({
    host: process.env.PGHOST,
    user: "emdash",
    database: "emdash",
    password,
    connectionTimeoutMillis: 3000,
  });
  await blocker.connect();
  try {
    await blocker.query("BEGIN");
    await blocker.query(
      "SELECT id FROM ec_campaign_pages WHERE id=$1 FOR UPDATE",
      [entry.id],
    );
    const started = performance.now();
    await assert.rejects(read, PublishedCampaignUnavailable);
    const elapsed = performance.now() - started;
    assert.ok(elapsed >= 900 && elapsed < 5000);
  } finally {
    await blocker.query("ROLLBACK");
    await blocker.end();
  }
  assert.deepEqual(await read(), restored);
  console.log(
    "published-campaign: real PostgreSQL live-only reads, draft and foreign-campaign isolation, next-read publish/withdrawal, missing binding, invalid selectors, scheduled/trash concealment, invalid content, guard failure/recovery and bounded row-lock failure/recovery passed; Core authorization, public HTTP/rendering, whole-request deadlines and media delivery remain pending",
  );
} finally {
  await database.destroy();
}
