import assert from "node:assert/strict";
import { randomBytes, createHash } from "node:crypto";
import pg from "pg";
import { Kysely, sql } from "kysely";
import { createDialect } from "emdash/db/postgres";
import { runMigrations } from "emdash/db";
import { MediaRepository } from "emdash";
import { provisionPostgres } from "./provision-postgres.mjs";
import {
  installCampaignMedia,
  requireCampaignMedia,
  createCampaignPendingMedia,
  getCampaignMedia,
  listCampaignMedia,
  findCampaignMediaByHash,
} from "../../apps/campaign-site/src/auth/campaign-media.mjs";

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
const a = "20000000-0000-4000-8000-000000000001";
const b = "20000000-0000-4000-8000-000000000002";
const actor = (actionId) => ({
  globalRoles: [],
  actionMemberships: [{ actionId, role: "charity_admin" }],
});
const system = { globalRoles: ["system_admin"], actionMemberships: [] };
const authorA = "01K00000000000000000000001";
const authorB = "01K00000000000000000000002";
const input = {
  filename: "synthetic.png",
  mimeType: "image/png",
  size: 68,
  authorId: authorA,
};
const hash = createHash("sha256").update("synthetic-image").digest("hex");
const missing = "01K00000000000000000000999";
const snapshot = async () => ({
  media: await database.selectFrom("media").selectAll().orderBy("id").execute(),
  bindings: await database
    .selectFrom("leonaid_campaign_media")
    .selectAll()
    .orderBy("media_id")
    .execute(),
});
try {
  await runMigrations(database);
  await assert.rejects(
    requireCampaignMedia(database),
    /campaign_media_version_mismatch/,
  );
  const repo = new MediaRepository(database);
  const unbound = await repo.create({
    ...input,
    storageKey: "legacy.png",
    contentHash: hash,
  });
  const installs = await Promise.all(
    Array.from({ length: 3 }, () => installCampaignMedia(database)),
  );
  assert.equal(installs.filter((result) => result.created).length, 1);
  assert.equal(await getCampaignMedia(database, system, a, unbound.id), null);
  assert.equal(await findCampaignMediaByHash(database, system, a, hash), null);
  assert.deepEqual(await listCampaignMedia(database, actor(a), a), {
    items: [],
    totalCount: 0,
    nextCursor: undefined,
  });
  const own1 = await createCampaignPendingMedia(database, actor(a), a, input);
  // Same uploader across campaigns and different uploader within a campaign:
  // author ownership is deliberately not the campaign authorization boundary.
  const foreign = await createCampaignPendingMedia(
    database,
    actor(b),
    b,
    input,
  );
  const own2 = await createCampaignPendingMedia(database, actor(a), a, {
    ...input,
    filename: "literal_%_name.png",
    authorId: authorB,
  });
  assert.notEqual(own1.storageKey, foreign.storageKey);
  assert.notEqual(own1.storageKey, own2.storageKey);
  assert.match(
    own1.storageKey,
    new RegExp(`^campaigns/${a}/[0-9a-f-]{36}\\.png$`),
  );
  assert.equal(own1.status, "pending");
  assert.equal((await listCampaignMedia(database, actor(a), a)).totalCount, 0);
  await repo.confirmUpload(foreign.id, { contentHash: hash });
  assert.equal(
    await findCampaignMediaByHash(database, actor(a), a, hash),
    null,
  );
  await repo.confirmUpload(own1.id, { contentHash: hash });
  await repo.confirmUpload(own2.id, { contentHash: hash });
  assert.equal(
    (await getCampaignMedia(database, actor(a), a, own2.id)).authorId,
    authorB,
  );
  assert.equal(await getCampaignMedia(database, actor(a), a, foreign.id), null);
  assert.equal(await getCampaignMedia(database, actor(a), a, missing), null);
  assert.equal(await getCampaignMedia(database, actor(a), a, "../file"), null);
  assert.equal(await getCampaignMedia(database, actor(a), a, unbound.id), null);
  assert.equal(
    (await getCampaignMedia(database, system, b, foreign.id)).id,
    foreign.id,
  );
  assert.equal(
    (await findCampaignMediaByHash(database, actor(a), a, hash)).id,
    [own1.id, own2.id].sort()[0],
  );
  const first = await listCampaignMedia(database, actor(a), a, { limit: 1 });
  const second = await listCampaignMedia(database, actor(a), a, {
    limit: 1,
    cursor: first.nextCursor,
  });
  assert.equal(first.totalCount, 2);
  assert.equal(second.totalCount, 2);
  assert.equal(second.nextCursor, undefined);
  assert.deepEqual(
    [...first.items, ...second.items].map((item) => item.id).sort(),
    [own1.id, own2.id].sort(),
  );
  const forgedCursor = await listCampaignMedia(database, actor(a), a, {
    cursor: foreign.id,
  });
  assert.equal(forgedCursor.totalCount, 2);
  assert.ok(
    forgedCursor.items.every((item) => [own1.id, own2.id].includes(item.id)),
  );
  assert.deepEqual(
    (await listCampaignMedia(database, actor(a), a, { q: "_%_" })).items.map(
      (item) => item.id,
    ),
    [own2.id],
  );
  const before = await snapshot();
  for (const profile of [
    actor(b),
    { globalRoles: ["finance_admin"], actionMemberships: [] },
    { globalRoles: [], actionMemberships: [] },
    null,
  ]) {
    for (const operation of [
      () => getCampaignMedia(database, profile, a, own1.id),
      () => listCampaignMedia(database, profile, a),
      () => findCampaignMediaByHash(database, profile, a, hash),
      () => createCampaignPendingMedia(database, profile, a, input),
    ])
      await assert.rejects(operation, /campaign_media_access_denied/);
  }
  for (const change of [
    { storageKey: own1.storageKey },
    { actionId: b },
    { mimeType: "image/svg+xml" },
    { mimeType: "text/html" },
    { size: 0 },
    { size: 8 * 1024 * 1024 + 1 },
    { size: 1.5 },
    { filename: "../escape.png" },
    { filename: "bad\\name.png" },
    { filename: "bad\u0000.png" },
    { authorId: "untrusted" },
    { contentHash: hash },
  ])
    await assert.rejects(
      createCampaignPendingMedia(database, actor(a), a, {
        ...input,
        ...change,
      }),
      /campaign_media_input_invalid/,
    );
  for (const query of [
    { actionId: b },
    { folderId: "global" },
    { limit: 101 },
    { limit: -1 },
    { cursor: "../escape" },
    { q: "x".repeat(201) },
  ])
    await assert.rejects(
      listCampaignMedia(database, actor(a), a, query),
      /campaign_media_input_invalid/,
    );
  await assert.rejects(
    database
      .updateTable("leonaid_campaign_media")
      .set({ action_id: b })
      .where("media_id", "=", own1.id)
      .execute(),
    { code: "23514" },
  );
  await assert.rejects(
    database
      .updateTable("leonaid_campaign_media")
      .set({ media_id: unbound.id })
      .where("media_id", "=", own1.id)
      .execute(),
    { code: "23514" },
  );
  await assert.rejects(
    database
      .deleteFrom("leonaid_campaign_media")
      .where("media_id", "=", own1.id)
      .execute(),
    { code: "23514" },
  );
  await assert.rejects(
    database
      .insertInto("leonaid_campaign_media")
      .values({ media_id: own1.id, action_id: b })
      .execute(),
    { code: "23505" },
  );
  await assert.rejects(
    database
      .insertInto("leonaid_campaign_media")
      .values({ media_id: missing, action_id: a })
      .execute(),
    { code: "23503" },
  );
  await assert.rejects(
    database
      .insertInto("leonaid_campaign_media")
      .values({ media_id: unbound.id, action_id: "invalid" })
      .execute(),
    { code: "23514" },
  );
  assert.deepEqual(await snapshot(), before);
  assert.deepEqual(await installCampaignMedia(database), { created: false });
  assert.deepEqual(await snapshot(), before);
  // Actual PostgreSQL failure after the media insert: no orphaned media row.
  await sql`CREATE FUNCTION public.synthetic_media_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic_media_failure'; END; $$`.execute(
    database,
  );
  await sql`CREATE TRIGGER synthetic_media_fail BEFORE INSERT ON public.leonaid_campaign_media FOR EACH ROW EXECUTE FUNCTION public.synthetic_media_fail()`.execute(
    database,
  );
  await assert.rejects(
    createCampaignPendingMedia(database, actor(a), a, input),
    /synthetic_media_failure/,
  );
  assert.deepEqual(await snapshot(), before);
  await sql`DROP TRIGGER synthetic_media_fail ON public.leonaid_campaign_media`.execute(
    database,
  );
  await sql`DROP FUNCTION public.synthetic_media_fail()`.execute(database);
  // Missing/disabled guards and schema drift are denied, not automatically repaired.
  await sql`ALTER TABLE public.leonaid_campaign_media DISABLE TRIGGER leonaid_campaign_media_guard`.execute(
    database,
  );
  for (const operation of [
    () => installCampaignMedia(database),
    () => getCampaignMedia(database, actor(a), a, own1.id),
    () => listCampaignMedia(database, actor(a), a),
    () => findCampaignMediaByHash(database, actor(a), a, hash),
    () => createCampaignPendingMedia(database, actor(a), a, input),
  ])
    await assert.rejects(operation, /campaign_media_guard_mismatch/);
  await sql`ALTER TABLE public.leonaid_campaign_media ENABLE TRIGGER leonaid_campaign_media_guard`.execute(
    database,
  );
  await database.transaction().execute(async (transaction) => {
    await sql`ALTER TABLE public.leonaid_campaign_media DROP CONSTRAINT leonaid_campaign_media_media_id_fkey`.execute(
      transaction,
    );
    await assert.rejects(
      requireCampaignMedia(transaction),
      /campaign_media_constraints_mismatch/,
    );
    // Restore the actual FK rather than weakening the expected contract.
    await sql`ALTER TABLE public.leonaid_campaign_media ADD CONSTRAINT leonaid_campaign_media_media_id_fkey FOREIGN KEY (media_id) REFERENCES public.media(id) ON DELETE CASCADE`.execute(
      transaction,
    );
  });
  await requireCampaignMedia(database);
  // Normal upstream removal cascades the obsolete binding; no orphan metadata.
  assert.equal(await repo.delete(own2.id), true);
  assert.equal(await getCampaignMedia(database, actor(a), a, own2.id), null);
  assert.equal((await listCampaignMedia(database, actor(a), a)).totalCount, 1);
  assert.equal(
    (await getCampaignMedia(database, actor(b), b, foreign.id)).id,
    foreign.id,
  );
  assert.equal((await repo.findById(unbound.id)).id, unbound.id);
  console.log(
    "campaign-media-binding: OK: real EmDash/PostgreSQL concurrent install, atomic pending creation/rollback, immutable ownership, scoped reads/count/search/pagination/hash lookup, foreign/unbound denial, drift denial and upstream deletion cascade. Profiles are policy inputs; HTTP, object upload and public delivery remain gated.",
  );
} finally {
  await database.destroy();
}
