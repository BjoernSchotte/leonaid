import {
  handleContentList,
  handleContentGet,
  handleRevisionList,
  handleRevisionGet,
  handleContentCompare,
} from "emdash";
import {
  requireCampaignMediaReferences,
  resolveCampaignEditorMedia,
} from "./campaign-media-references.mjs";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Input must be the current, server-validated Core profile, never request JSON.
// This primitive does not enable any HTTP route or global CMS role.
export function campaignListParameters(profile, collection, parameters = {}) {
  if (collection !== "campaign_pages")
    throw new Error("campaign_access_denied");
  if (profile.globalRoles.includes("system_admin")) return { ...parameters };
  const actions = [
    ...new Set(
      profile.actionMemberships
        .filter((membership) => membership.role === "charity_admin")
        .map((membership) => membership.actionId),
    ),
  ];
  if (actions.length === 0 || actions.some((id) => !uuid.test(id))) {
    throw new Error("campaign_access_denied");
  }
  return {
    ...parameters,
    fieldFilters: {
      ...parameters.fieldFilters,
      // Override, never merge with, a caller-selected action binding.
      action_id: { in: actions },
    },
  };
}

export async function listCampaignContent(
  database,
  profile,
  collection,
  parameters = {},
) {
  return database.transaction().execute(async (transaction) => {
    const result = await handleContentList(
      transaction,
      collection,
      campaignListParameters(profile, collection, parameters),
    );
    if (result.success)
      for (const item of result.data.items)
        await requireCampaignMediaReferences(
          transaction,
          item.data.action_id,
          item.data,
        );
    return result;
  });
}

const ulid = /^[0-9A-HJKMNP-TV-Z]{26}$/;
const notFound = () => ({
  success: false,
  error: { code: "NOT_FOUND", message: "Content not found" },
});

function scopedEntryQuery(database, profile, collection) {
  const parameters = campaignListParameters(profile, collection);
  // Fixed, pinned EmDash table contract; never interpolate a request collection.
  // Select only authorization metadata before invoking upstream content readers.
  let query = database
    .selectFrom("ec_campaign_pages")
    .select(["ec_campaign_pages.id", "ec_campaign_pages.action_id"])
    .where("ec_campaign_pages.deleted_at", "is", null);
  if (parameters.fieldFilters) {
    query = query.where(
      "ec_campaign_pages.action_id",
      "in",
      parameters.fieldFilters.action_id.in,
    );
  }
  return query;
}

export async function getCampaignContent(database, profile, collection, id) {
  campaignListParameters(profile, collection);
  if (!ulid.test(id)) return notFound();
  return database.transaction().execute(async (transaction) => {
    const entry = await scopedEntryQuery(transaction, profile, collection)
      .where("ec_campaign_pages.id", "=", id)
      .forShare()
      .executeTakeFirst();
    if (!entry) return notFound();
    // Hold the row lock through hydration; concurrent rebinding/deletion cannot
    // change the authorization target between lookup and upstream data access.
    const result = await handleContentGet(transaction, collection, entry.id);
    if (result.success)
      result.data.item.data = await resolveCampaignEditorMedia(
        transaction,
        entry.action_id,
        result.data.item.data,
      );
    return result;
  });
}

export async function listCampaignRevisions(
  database,
  profile,
  collection,
  id,
  parameters = {},
) {
  campaignListParameters(profile, collection);
  if (!ulid.test(id)) return notFound();
  return database.transaction().execute(async (transaction) => {
    const entry = await scopedEntryQuery(transaction, profile, collection)
      .where("ec_campaign_pages.id", "=", id)
      .forShare()
      .executeTakeFirst();
    if (!entry) return notFound();
    const result = await handleRevisionList(
      transaction,
      collection,
      entry.id,
      parameters,
    );
    if (result.success)
      for (const revision of result.data.items)
        await requireCampaignMediaReferences(
          transaction,
          entry.action_id,
          revision.data,
        );
    return result;
  });
}

export async function getCampaignRevision(database, profile, revisionId) {
  campaignListParameters(profile, "campaign_pages");
  if (!ulid.test(revisionId)) return notFound();
  return database.transaction().execute(async (transaction) => {
    const entry = await scopedEntryQuery(transaction, profile, "campaign_pages")
      .innerJoin("revisions", "revisions.entry_id", "ec_campaign_pages.id")
      .where("revisions.collection", "=", "campaign_pages")
      .where("revisions.id", "=", revisionId)
      .forShare()
      .executeTakeFirst();
    if (!entry) return notFound();
    // Permission derives from the stored parent, never revision JSON or a
    // caller-supplied entry ID. Lock both rows until the revision is read.
    const result = await handleRevisionGet(transaction, revisionId);
    if (result.success)
      await requireCampaignMediaReferences(
        transaction,
        entry.action_id,
        result.data.item.data,
      );
    return result;
  });
}

export async function compareCampaignContent(
  database,
  profile,
  collection,
  id,
) {
  campaignListParameters(profile, collection);
  if (!ulid.test(id)) return notFound();
  return database.transaction().execute(async (transaction) => {
    const entry = await scopedEntryQuery(transaction, profile, collection)
      .select(["live_revision_id", "draft_revision_id"])
      .where("ec_campaign_pages.id", "=", id)
      .forShare()
      .executeTakeFirst();
    if (!entry) return notFound();
    const ids = [
      ...new Set(
        [entry.live_revision_id, entry.draft_revision_id].filter(Boolean),
      ),
    ];
    if (ids.length) {
      const revisions = await transaction
        .selectFrom("revisions")
        .select(["id", "data"])
        .where("collection", "=", collection)
        .where("entry_id", "=", id)
        .where("id", "in", ids)
        .forShare()
        .execute();
      if (revisions.length !== ids.length) return notFound();
      for (const revision of revisions)
        await requireCampaignMediaReferences(
          transaction,
          entry.action_id,
          typeof revision.data === "string"
            ? JSON.parse(revision.data)
            : revision.data,
        );
    }
    return handleContentCompare(transaction, collection, id);
  });
}
