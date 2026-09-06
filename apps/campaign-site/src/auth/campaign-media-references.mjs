import { campaignImageReference } from "./campaign-editorial.mjs";
import { requireCampaignMedia } from "./campaign-media.mjs";

export class CampaignMediaReferenceError extends Error {
  constructor() {
    super("campaign_media_reference_denied");
    this.status = 403;
  }
}

export async function requireCampaignResultMediaReferences(
  transaction,
  actionId,
  result,
) {
  const data = result?.data?.item?.data;
  if (!data || typeof data !== "object" || Array.isArray(data))
    throw new Error("campaign_mutation_result_invalid");
  await requireCampaignMediaReferences(transaction, actionId, data);
}

// Caller holds the content/revision transaction. Lock media and immutable
// binding rows through commit, before upstream normalization can perform a
// global provider lookup. Author ownership and hashes never grant access.
export async function requireCampaignMediaReferences(
  transaction,
  actionId,
  data,
) {
  const refs = [
    data?.hero_image,
    data?.social_image,
    ...(Array.isArray(data?.partners)
      ? data.partners.map((partner) => partner?.logo)
      : []),
  ].filter((value) => value !== null && value !== undefined);
  if (!refs.length) return;
  if (
    refs.length > 32 ||
    refs.some((value) => !campaignImageReference.safeParse(value).success)
  )
    throw new CampaignMediaReferenceError();
  await requireCampaignMedia(transaction);
  const ids = [...new Set(refs.map((value) => value.id))].sort();
  const rows = await transaction
    .selectFrom("media")
    .innerJoin(
      "leonaid_campaign_media",
      "leonaid_campaign_media.media_id",
      "media.id",
    )
    .select([
      "media.id",
      "media.storage_key",
      "media.width",
      "media.height",
      "media.filename",
      "media.mime_type",
      "media.content_hash",
      "media.caption",
      "media.blurhash",
      "media.dominant_color",
    ])
    .where("leonaid_campaign_media.action_id", "=", actionId)
    .where("media.id", "in", ids)
    .where("media.status", "=", "ready")
    .orderBy("media.id")
    .forShare()
    .execute();
  if (rows.length !== ids.length) throw new CampaignMediaReferenceError();
  for (const ref of refs) {
    const row = rows.find((item) => item.id === ref.id);
    if (
      !row ||
      !campaignImageReference.safeParse({
        id: row.id,
        meta: { storageKey: row.storage_key },
      }).success ||
      !row.storage_key.startsWith(`campaigns/${actionId}/`) ||
      !/^[0-9a-f]{64}$/.test(row.content_hash ?? "") ||
      !["image/png", "image/jpeg", "image/webp"].includes(row.mime_type) ||
      !Number.isInteger(row.width) ||
      row.width < 1 ||
      row.width > 8192 ||
      !Number.isInteger(row.height) ||
      row.height < 1 ||
      row.height > 8192 ||
      (ref.meta && ref.meta.storageKey !== row.storage_key) ||
      (ref.meta &&
        Object.entries({
          caption: row.caption,
          blurhash: row.blurhash,
          dominantColor: row.dominant_color,
        }).some(
          ([key, value]) =>
            ref.meta[key] !== undefined && ref.meta[key] !== value,
        )) ||
      Object.entries({
        width: row.width,
        height: row.height,
        filename: row.filename,
        mimeType: row.mime_type,
      }).some(([key, value]) => ref[key] !== undefined && ref[key] !== value)
    )
      throw new CampaignMediaReferenceError();
  }
}
