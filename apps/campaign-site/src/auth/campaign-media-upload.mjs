import { randomUUID } from "node:crypto";
import { sql } from "kysely";
import { MediaRepository } from "emdash";
import { getCampaignMedia, requireCampaignMedia } from "./campaign-media.mjs";
import { normalizeCampaignImage } from "./campaign-image.mjs";

// Claim through the actual upstream attempt ledger before deletion. A key still
// referenced by ANY media row must survive, including after ambiguous commits.
async function cleanAttempt(database, storage, key) {
  const repository = new MediaRepository(database);
  if (await repository.claimUploadAttemptForCleanup(key)) {
    await storage.delete(key);
    await repository.deleteUploadAttempt(key);
  }
}

// Private upload staging only; this never marks media ready/public. The HTTP
// coordinator must use a fresh Core profile and recheck authority during final
// confirmation. Original media size/type remain the PUT contract until confirm.
export async function stageCampaignImageUpload(
  database,
  storage,
  profile,
  actionId,
  id,
  bytes,
  mimeType,
) {
  const item = await getCampaignMedia(database, profile, actionId, id);
  if (!item) throw new Error("campaign_media_not_found");
  if (item.status !== "pending")
    throw new Error("campaign_media_upload_conflict");
  if (
    !(bytes instanceof Uint8Array) ||
    bytes.byteLength !== item.size ||
    mimeType !== item.mimeType
  )
    throw new Error("campaign_image_invalid");
  const image = await normalizeCampaignImage(bytes, mimeType);
  const extension = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
  }[mimeType];
  const key = `campaigns/${actionId}/${randomUUID()}.${extension}`;
  const repository = new MediaRepository(database);
  // Durable before object PUT: a crash or DB outage leaves a private, tracked
  // attempt for upstream cleanup, not an untracked public object.
  await repository.createUploadAttempt(id, key);
  try {
    const uploaded = await storage.upload({
      key,
      body: image.bytes,
      contentType: image.mimeType,
    });
    if (uploaded.key !== key || uploaded.size !== image.size)
      throw new Error("campaign_media_storage_invalid");
    await database.transaction().execute(async (transaction) => {
      await sql`SET LOCAL lock_timeout = '2s'`.execute(transaction);
      await sql`SET LOCAL statement_timeout = '3s'`.execute(transaction);
      await requireCampaignMedia(transaction);
      const current = await transaction
        .selectFrom("media")
        .innerJoin(
          "leonaid_campaign_media",
          "leonaid_campaign_media.media_id",
          "media.id",
        )
        .select(["media.storage_key", "media.status"])
        .where("media.id", "=", id)
        .where("leonaid_campaign_media.action_id", "=", actionId)
        .forUpdate()
        .executeTakeFirst();
      if (
        !current ||
        current.status !== "pending" ||
        current.storage_key !== item.storageKey
      )
        throw new Error("campaign_media_upload_conflict");
      const committed = await new MediaRepository(
        transaction,
      ).publishPendingStorageKey(id, item.storageKey, key, image.contentHash);
      if (!committed) throw new Error("campaign_media_upload_conflict");
    });
  } catch (error) {
    // If DB state cannot be checked, retain the durable attempt. Never blindly
    // delete a key that an uncertain transaction may have successfully linked.
    try {
      await cleanAttempt(database, storage, key);
    } catch {
      /* deferred cleanup */
    }
    throw new Error(
      error instanceof Error &&
      error.message === "campaign_media_upload_conflict"
        ? "campaign_media_upload_conflict"
        : "campaign_media_upload_failed",
    );
  }
  // A prior staged attempt can be removed only after the replacement is linked.
  // Initial reservations have no attempt/object and are not deleted here.
  try {
    await cleanAttempt(database, storage, item.storageKey);
  } catch {
    /* deferred cleanup */
  }
  return { uploaded: true, size: bytes.byteLength };
}
