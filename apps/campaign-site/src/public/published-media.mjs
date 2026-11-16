import { readPublishedCampaign } from "./published-campaign.mjs";

const slugPattern = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const idPattern = /^[0-9A-HJKMNP-TV-Z]{26}$/;
const hashPattern = /^[0-9a-f]{64}$/;
// The URL names the first 16 hex digits (64 bits) of the content hash. A
// different file never shares a URL with the old one, so a browser may keep
// a versioned image for a year without asking again (E-067).
export const mediaVersionLength = 16;
// Widths the server renders on request. Larger originals are scaled down,
// never up; a request for another width is refused.
export const mediaWidths = Object.freeze([480, 960, 1440, 1920]);
// Cache answer of a versioned image; every other public answer is no-store.
export const versionedMediaCache = "public, max-age=31536000, immutable";

export function mediaVersion(contentHash) {
  if (typeof contentHash !== "string" || !hashPattern.test(contentHash))
    throw new Error("invalid_public_media_hash");
  return contentHash.slice(0, mediaVersionLength);
}

// Media IDs never change their file: a replacement upload gets a new ID and
// an old URL stops working as soon as the published page no longer
// references it. With a content hash, the URL is versioned for caching too.
export function publicMediaPath(slug, id, { contentHash, width } = {}) {
  if (!slugPattern.test(slug) || !idPattern.test(id))
    throw new Error("invalid_public_media_path");
  const path = `/campaigns/${slug}/media/${id}`;
  if (contentHash === undefined) return path;
  const query = new URLSearchParams({ v: mediaVersion(contentHash) });
  if (width !== undefined) {
    if (!mediaWidths.includes(width))
      throw new Error("invalid_public_media_width");
    query.set("w", String(width));
  }
  return `${path}?${query}`;
}

// `srcset` for an image of the published page: every rendered width below
// the original plus the original itself. Null when no smaller width exists.
export function publicMediaSrcset(slug, id, { contentHash, width }) {
  if (!Number.isInteger(width) || width < 1) return null;
  const smaller = mediaWidths.filter((candidate) => candidate < width);
  if (!smaller.length) return null;
  return [
    ...smaller.map(
      (candidate) =>
        `${publicMediaPath(slug, id, { contentHash, width: candidate })} ${candidate}w`,
    ),
    `${publicMediaPath(slug, id, { contentHash })} ${width}w`,
  ].join(", ");
}

// The published page's media references, keyed by the live row's identity.
// A publish, unpublish, edit or deletion changes that key, so the next
// request validates the full page again (readPublishedCampaign). Between
// changes a request costs two small queries instead of hydrating and
// validating the whole page.
const references = new Map();
const referenceEntries = 64;

async function publishedRowKey(database, actionId) {
  const row = await database
    .selectFrom("ec_campaign_pages")
    .select([
      "id",
      "version",
      "updated_at",
      "live_revision_id",
      "status",
      "deleted_at",
    ])
    .where("action_id", "=", actionId)
    .where("status", "=", "published")
    .where("deleted_at", "is", null)
    .executeTakeFirst();
  if (!row) return null;
  return [
    row.id,
    row.version,
    String(row.updated_at),
    row.live_revision_id ?? "",
  ].join("|");
}

async function publishedReferenceIds(database, actionId) {
  const key = await publishedRowKey(database, actionId);
  if (key === null) {
    references.delete(actionId);
    return null;
  }
  const cached = references.get(actionId);
  if (cached?.key === key) return cached.ids;
  const page = await readPublishedCampaign(database, actionId);
  if (!page) {
    references.delete(actionId);
    return null;
  }
  const ids = new Set(
    [
      page.data.hero_image,
      page.data.social_image,
      page.data.brand_logo,
      ...(page.data.partners ?? []).map((partner) => partner.logo),
    ]
      .filter(Boolean)
      .map((reference) => reference.id),
  );
  references.delete(actionId);
  references.set(actionId, { key, ids });
  if (references.size > referenceEntries)
    references.delete(references.keys().next().value);
  return ids;
}

export async function readPublishedMedia(database, actionId, id) {
  if (typeof id !== "string" || !idPattern.test(id)) return null;
  const ids = await publishedReferenceIds(database, actionId);
  if (!ids?.has(id)) return null;
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

export function forgetPublishedMediaReferences() {
  references.clear();
}

// `src` and `srcset` of a page image. `media` is readPublishedCampaign's map
// of content hashes and widths; without an entry the URL stays unversioned.
export function campaignImageSources(slug, id, media) {
  const facts = media?.[id];
  if (!facts) return { src: publicMediaPath(slug, id), srcset: undefined };
  return {
    src: publicMediaPath(slug, id, { contentHash: facts.contentHash }),
    srcset: publicMediaSrcset(slug, id, facts) ?? undefined,
  };
}
