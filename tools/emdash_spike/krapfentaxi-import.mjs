import { createHash, randomUUID } from "node:crypto";
import { isDeepStrictEqual } from "node:util";
import { requireCampaignSchema } from "../../apps/campaign-site/src/install-campaign-schema.mjs";
import { sql } from "kysely";
import { MediaRepository, ContentRepository } from "emdash";
import { requireCampaignBindings } from "../../apps/campaign-site/src/auth/campaign-bindings.mjs";
import { requireCampaignMedia } from "../../apps/campaign-site/src/auth/campaign-media.mjs";
import { requireCampaignMediaReferences } from "../../apps/campaign-site/src/auth/campaign-media-references.mjs";
import { stageCampaignImageUpload } from "../../apps/campaign-site/src/auth/campaign-media-upload.mjs";
import { normalizeCampaignImage } from "../../apps/campaign-site/src/auth/campaign-image.mjs";
import {
  loadKrapfentaxiSource,
  krapfentaxiImportData,
} from "./krapfentaxi-source.mjs";

const versionName = "leonaid:krapfentaxi_import_journal_version";
const hash = (bytes) => createHash("sha256").update(bytes).digest("hex");
const fail = (reason) => {
  throw new Error(`krapfentaxi_import_${reason}`);
};
async function bounded(transaction) {
  await sql`SET LOCAL lock_timeout='3s'`.execute(transaction);
  await sql`SET LOCAL statement_timeout='5s'`.execute(transaction);
}
async function journalExists(database) {
  const row = (
    await sql`SELECT to_regclass('public.leonaid_krapfentaxi_import') AS relation`.execute(
      database,
    )
  ).rows[0];
  return row.relation !== null;
}
async function requireJournal(database) {
  const version = await database
    .selectFrom("options")
    .select("value")
    .where("name", "=", versionName)
    .executeTakeFirst();
  if (version?.value !== "1") fail("journal_version");
  const columns = (
    await sql`SELECT attname, format_type(atttypid,atttypmod) AS type, attnotnull AS required
    FROM pg_attribute WHERE attrelid='public.leonaid_krapfentaxi_import'::regclass AND attnum>0 AND NOT attisdropped ORDER BY attnum`.execute(
      database,
    )
  ).rows;
  const expected = [
    ["action_id", "text", true],
    ["core_user_id", "text", true],
    ["author_id", "text", true],
    ["fingerprint", "text", true],
    ["manifest", "jsonb", true],
    ["media", "jsonb", true],
    ["content_id", "text", false],
  ];
  if (
    JSON.stringify(columns) !==
    JSON.stringify(
      expected.map(([attname, type, required]) => ({
        attname,
        type,
        required,
      })),
    )
  )
    fail("journal_drift");
  const primary = (
    await sql`SELECT pg_get_constraintdef(oid) AS definition FROM pg_constraint
    WHERE conrelid='public.leonaid_krapfentaxi_import'::regclass AND contype='p' AND convalidated AND NOT condeferrable`.execute(
      database,
    )
  ).rows;
  if (
    primary.length !== 1 ||
    primary[0].definition !== "PRIMARY KEY (action_id)"
  )
    fail("journal_drift");
}
async function installJournal(database) {
  await database.transaction().execute(async (transaction) => {
    await bounded(transaction);
    await sql`SELECT pg_advisory_xact_lock(724381917)`.execute(transaction);
    if (await journalExists(transaction)) return requireJournal(transaction);
    await sql`CREATE TABLE public.leonaid_krapfentaxi_import (
      action_id text PRIMARY KEY,
      core_user_id text NOT NULL,
      author_id text NOT NULL,
      fingerprint text NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
      manifest jsonb NOT NULL,
      media jsonb NOT NULL,
      content_id text REFERENCES public.ec_campaign_pages(id)
    )`.execute(transaction);
    await transaction
      .insertInto("options")
      .values({ name: versionName, value: "1" })
      .execute();
    await requireJournal(transaction);
  });
}

// Operator coordinator, not an HTTP route. resolveTarget must use fresh Core
// identity/action reads and return an existing synchronized CMS identity. It is
// called after write locks too; no profile from a CLI payload grants authority.
// The journal is private operator metadata, never an editable CMS collection.
export async function importKrapfentaxi({
  database,
  storage,
  resolveTarget,
  mode,
  checkpoint = async () => {},
}) {
  if (!["dry-run", "apply"].includes(mode)) fail("mode");
  const source = await loadKrapfentaxiSource();
  const initial = await resolveTarget();
  const actionId = initial.action.id;
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
      actionId,
    )
  )
    fail("target");
  const authority = async (db) => {
    const current = await resolveTarget();
    if (
      current.action.id !== actionId ||
      current.action.archiveSlug !== initial.action.archiveSlug ||
      current.profile.userId !== initial.profile.userId ||
      current.authorId !== initial.authorId ||
      (!current.profile.globalRoles.includes("system_admin") &&
        !current.profile.actionMemberships.some(
          (membership) =>
            membership.actionId === actionId &&
            membership.role === "charity_admin",
        ))
    )
      fail("authority");
    const mapping = await db
      .selectFrom("leonaid_external_identity")
      .select("cms_user_id")
      .where("core_user_id", "=", current.profile.userId)
      .where("cms_user_id", "=", current.authorId)
      .executeTakeFirst();
    if (!mapping) fail("identity_mapping");
    return current;
  };
  await requireCampaignBindings(database);
  await requireCampaignMedia(database);
  await requireCampaignSchema(database);
  await authority(database);
  const inspect = async (db) => {
    const exists = await journalExists(db);
    if (exists) await requireJournal(db);
    const job = exists
      ? await db
          .selectFrom("leonaid_krapfentaxi_import")
          .selectAll()
          .where("action_id", "=", actionId)
          .executeTakeFirst()
      : null;
    const content = await db
      .selectFrom("ec_campaign_pages")
      .select("id")
      .where("action_id", "=", actionId)
      .executeTakeFirst();
    if (
      job &&
      (job.fingerprint !== source.fingerprint ||
        !isDeepStrictEqual(job.manifest, source.manifest) ||
        job.core_user_id !== initial.profile.userId ||
        job.author_id !== initial.authorId ||
        !job.media ||
        Array.isArray(job.media) ||
        Object.entries(job.media).some(
          ([key, id]) =>
            !["hero", "logo", "partner"].includes(key) ||
            typeof id !== "string" ||
            !/^[0-9A-HJKMNP-TV-Z]{26}$/.test(id),
        ))
    )
      fail("journal_conflict");
    if (content && content.id !== job?.content_id)
      fail("existing_editorial_content");
    if (job?.content_id && !content) fail("imported_content_missing");
    return {
      job,
      state: job?.content_id ? "preserved" : job ? "resume" : "create",
    };
  };
  if (mode === "dry-run") {
    const result = await inspect(database);
    return {
      mode,
      state: result.state,
      fingerprint: source.fingerprint,
      assets: 3,
      publishes: false,
    };
  }
  // One dedicated connection holds a session lock across separate durable
  // transactions/S3 calls. A killed process releases the lock, not the journal.
  return database.connection().execute(async (connection) => {
    const lock = (
      await sql`SELECT pg_try_advisory_lock(hashtextextended(${actionId},724381916)) AS acquired`.execute(
        connection,
      )
    ).rows[0];
    if (!lock.acquired) fail("busy");
    try {
      await authority(connection);
      const inspected = await inspect(connection);
      if (inspected.state === "preserved")
        return {
          mode,
          state: "preserved",
          fingerprint: source.fingerprint,
          contentId: inspected.job.content_id,
        };
      await installJournal(connection);
      await connection.transaction().execute(async (transaction) => {
        await bounded(transaction);
        await authority(transaction);
        if (!(await inspect(transaction)).job)
          await transaction
            .insertInto("leonaid_krapfentaxi_import")
            .values({
              action_id: actionId,
              core_user_id: initial.profile.userId,
              author_id: initial.authorId,
              fingerprint: source.fingerprint,
              manifest: JSON.stringify(source.manifest),
              media: "{}",
              content_id: null,
            })
            .execute();
      });
      const references = {};
      for (const asset of source.assets) {
        const expected = await normalizeCampaignImage(
          asset.bytes,
          asset.mimeType,
        );
        const id = await connection
          .transaction()
          .execute(async (transaction) => {
            await bounded(transaction);
            await authority(transaction);
            const job = await transaction
              .selectFrom("leonaid_krapfentaxi_import")
              .selectAll()
              .where("action_id", "=", actionId)
              .forUpdate()
              .executeTakeFirstOrThrow();
            if (job.media[asset.key]) return job.media[asset.key];
            const item = await new MediaRepository(transaction).createPending({
              filename: asset.filename,
              mimeType: asset.mimeType,
              size: asset.bytes.length,
              authorId: initial.authorId,
              storageKey: `campaigns/${actionId}/${randomUUID()}.${asset.filename.split(".").at(-1)}`,
            });
            await transaction
              .insertInto("leonaid_campaign_media")
              .values({ media_id: item.id, action_id: actionId })
              .execute();
            await transaction
              .updateTable("leonaid_krapfentaxi_import")
              .set({
                media: JSON.stringify({ ...job.media, [asset.key]: item.id }),
              })
              .where("action_id", "=", actionId)
              .execute();
            return item.id;
          });
        await checkpoint("reserved", asset.key);
        let item = await new MediaRepository(connection).findById(id);
        const binding = await connection
          .selectFrom("leonaid_campaign_media")
          .select("action_id")
          .where("media_id", "=", id)
          .executeTakeFirst();
        if (!item || binding?.action_id !== actionId) fail("media_binding");
        if (item.status === "pending") {
          await stageCampaignImageUpload(
            connection,
            storage,
            initial.profile,
            actionId,
            id,
            asset.bytes,
            asset.mimeType,
            authority,
          );
          item = await new MediaRepository(connection).findById(id);
        } else if (item.status !== "ready") fail("media_state");
        const stored = await storage.download(item.storageKey);
        if (
          item.contentHash !== expected.contentHash ||
          stored.contentType !== asset.mimeType ||
          stored.size !== expected.size ||
          hash(stored.bytes) !== expected.contentHash
        )
          fail("media_integrity");
        const ready = await connection
          .transaction()
          .execute(async (transaction) => {
            await bounded(transaction);
            const current = await transaction
              .selectFrom("media")
              .selectAll()
              .where("id", "=", id)
              .forUpdate()
              .executeTakeFirstOrThrow();
            await authority(transaction);
            if (
              current.storage_key !== item.storageKey ||
              current.content_hash !== expected.contentHash
            )
              fail("media_conflict");
            const repository = new MediaRepository(transaction);
            if (current.status === "ready") return repository.findById(id);
            if (
              current.status !== "pending" ||
              !(await repository.hasUploadAttempt(item.storageKey))
            )
              fail("media_state");
            const result = await repository.confirmUpload(
              id,
              {
                size: stored.size,
                width: expected.width,
                height: expected.height,
                contentHash: expected.contentHash,
              },
              item.storageKey,
            );
            if (!result) fail("media_conflict");
            await repository.deleteUploadAttempt(item.storageKey);
            return result;
          });
        if (
          ready.width !== expected.width ||
          ready.height !== expected.height ||
          ready.mimeType !== asset.mimeType
        )
          fail("media_metadata");
        references[asset.key] = { ...ready, actionId };
        await checkpoint("ready", asset.key);
      }
      const contentId = await connection
        .transaction()
        .execute(async (transaction) => {
          await bounded(transaction);
          // Same lock as native campaign creation; no race may overwrite a page.
          await sql`SELECT pg_advisory_xact_lock(hashtextextended(${actionId},724381903))`.execute(
            transaction,
          );
          await authority(transaction);
          const state = await inspect(transaction);
          if (state.job?.content_id) return state.job.content_id;
          const data = krapfentaxiImportData(actionId, references);
          await requireCampaignMediaReferences(transaction, actionId, data);
          // A bounded operator import has no taxonomies, bylines or independent
          // SEO/locale operations. Use EmDash's repository directly so an upstream
          // HTTP handler cannot log raw database exceptions on an operator failure.
          const item = await new ContentRepository(transaction).create({
            type: "campaign_pages",
            data,
            slug: actionId,
            status: "draft",
            authorId: initial.authorId,
          });
          if (!item?.id) fail("content_create");
          await transaction
            .updateTable("leonaid_krapfentaxi_import")
            .set({ content_id: item.id })
            .where("action_id", "=", actionId)
            .execute();
          await authority(transaction);
          return item.id;
        });
      await checkpoint("complete");
      return {
        mode,
        state: "imported",
        fingerprint: source.fingerprint,
        contentId,
        published: false,
      };
    } finally {
      await sql`SELECT pg_advisory_unlock(hashtextextended(${actionId},724381916))`.execute(
        connection,
      );
    }
  });
}
