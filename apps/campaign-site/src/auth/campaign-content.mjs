import { handleContentList } from "emdash";

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
