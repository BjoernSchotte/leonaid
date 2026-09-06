import {
  handleContentList,
  handleContentGet,
  handleRevisionList,
  handleRevisionGet,
} from "emdash";

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
  return handleContentList(
    database,
    collection,
    campaignListParameters(profile, collection, parameters),
  );
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
    .select("ec_campaign_pages.id")
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
    return handleContentGet(transaction, collection, entry.id);
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
    return handleRevisionList(transaction, collection, entry.id, parameters);
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
    return handleRevisionGet(transaction, revisionId);
  });
}
