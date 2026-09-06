// Only these proven read handlers may pass the outer default-deny boundary.
// IDs are canonical EmDash ULIDs; public slugs are resolved separately by Core.
const id = "[0-9A-HJKMNP-TV-Z]{26}";
const content = new RegExp(
  `^/_emdash/api/content/campaign_pages(?:/${id}(?:/(?:revisions|compare))?)?$`,
);
const revision = new RegExp(`^/_emdash/api/revisions/${id}$`);

export function isCampaignReadRoute(path, method) {
  return method === "GET" && (content.test(path) || revision.test(path));
}

const update = new RegExp(`^/_emdash/api/content/campaign_pages/${id}$`);
export function isCampaignUpdateRoute(path, method) {
  return method === "PUT" && update.test(path);
}

const restore = new RegExp(`^/_emdash/api/revisions/${id}/restore$`);
export function isCampaignRestoreRoute(path, method) {
  return method === "POST" && restore.test(path);
}

const discard = new RegExp(
  `^/_emdash/api/content/campaign_pages/${id}/discard-draft$`,
);
export function isCampaignDiscardRoute(path, method) {
  return method === "POST" && discard.test(path);
}
