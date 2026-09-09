import assert from "node:assert/strict";
import { Kysely } from "kysely";
import { createDialect } from "emdash/db/postgres";
import { getCampaignContent } from "../../apps/campaign-site/src/auth/campaign-content.mjs";
import { resolveCampaignEditorMedia } from "../../apps/campaign-site/src/auth/campaign-media-references.mjs";

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
  const actionId = "20000000-0000-4000-8000-000000000001";
  const entry = await database
    .selectFrom("ec_campaign_pages")
    .selectAll()
    .where("action_id", "=", actionId)
    .executeTakeFirstOrThrow();
  const revisions = await database
    .selectFrom("revisions")
    .selectAll()
    .where("entry_id", "=", entry.id)
    .orderBy("id")
    .execute();
  const result = await getCampaignContent(
    database,
    { globalRoles: ["system_admin"] },
    "campaign_pages",
    entry.id,
  );
  assert.equal(result.success, true);
  const data = result.data.item.data;
  for (const ref of [
    data.hero_image,
    data.social_image,
    data.brand_logo,
    data.partners[0].logo,
  ]) {
    assert.ok(ref.meta.storageKey.startsWith(`campaigns/${actionId}/`));
    assert.notEqual(ref.meta.storageKey, ref.id);
  }
  const minimal = structuredClone(data);
  for (const ref of [
    minimal.hero_image,
    minimal.social_image,
    minimal.brand_logo,
    minimal.partners[0].logo,
  ])
    delete ref.meta;
  const original = structuredClone(minimal);
  await database.transaction().execute(async (transaction) => {
    const resolved = await resolveCampaignEditorMedia(
      transaction,
      actionId,
      minimal,
    );
    assert.deepEqual(minimal, original);
    assert.deepEqual(resolved.hero_image.meta, data.hero_image.meta);
    await assert.rejects(
      resolveCampaignEditorMedia(
        transaction,
        "20000000-0000-4000-8000-000000000003",
        minimal,
      ),
    );
    const tampered = structuredClone(data);
    tampered.hero_image.meta.storageKey =
      "campaigns/20000000-0000-4000-8000-000000000003/10000000-0000-4000-8000-000000000001.png";
    await assert.rejects(
      resolveCampaignEditorMedia(transaction, actionId, tampered),
    );
  });
  assert.deepEqual(
    await database
      .selectFrom("ec_campaign_pages")
      .selectAll()
      .where("id", "=", entry.id)
      .executeTakeFirstOrThrow(),
    entry,
  );
  assert.deepEqual(
    await database
      .selectFrom("revisions")
      .selectAll()
      .where("entry_id", "=", entry.id)
      .orderBy("id")
      .execute(),
    revisions,
  );
  console.log(
    "local-editor-media: bound paths resolved; foreign campaign and forged path denied; input, content and revisions unchanged",
  );
} finally {
  await database.destroy();
}
