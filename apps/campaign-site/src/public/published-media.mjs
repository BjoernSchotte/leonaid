import { readPublishedCampaign } from "./published-campaign.mjs";

// Immutable media IDs version URLs. Replacement uploads get a new ID; an old
// URL ceases to work as soon as the published document no longer references it.
export function publicMediaPath(slug, id) {
  if (
    !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug) ||
    !/^[0-9A-HJKMNP-TV-Z]{26}$/.test(id)
  )
    throw new Error("invalid_public_media_path");
  return `/campaigns/${slug}/media/${id}`;
}

export async function readPublishedMedia(database, actionId, id) {
  if (typeof id !== "string" || !/^[0-9A-HJKMNP-TV-Z]{26}$/.test(id))
    return null;
  const page = await readPublishedCampaign(database, actionId);
  if (!page) return null;
  const references = [
    page.data.hero_image,
    page.data.social_image,
    page.data.brand_logo,
    ...(page.data.partners ?? []).map((partner) => partner.logo),
  ];
  if (!references.some((reference) => reference?.id === id)) return null;
  // The live-only reader has validated all reference ownership/cached facts.
  // Resolve only this campaign's ready object, never a caller-supplied S3 key.
  return (
    (await database
      .selectFrom("media")
      .innerJoin(
        "leonaid_campaign_media",
        "leonaid_campaign_media.media_id",
        "media.id",
      )
      .select([
        "media.id",
        "media.storage_key",
        "media.mime_type",
        "media.content_hash",
        "media.width",
        "media.height",
      ])
      .where("leonaid_campaign_media.action_id", "=", actionId)
      .where("media.id", "=", id)
      .where("media.status", "=", "ready")
      .executeTakeFirst()) ?? null
  );
}
