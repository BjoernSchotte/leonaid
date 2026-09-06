// Only these proven read handlers may pass the outer default-deny boundary.
// IDs are canonical EmDash ULIDs; public slugs are resolved separately by Core.
const id = "[0-9A-HJKMNP-TV-Z]{26}";
const content = new RegExp(
  `^/_emdash/api/content/campaign_pages(?:/${id}(?:/revisions)?)?$`,
);
const revision = new RegExp(`^/_emdash/api/revisions/${id}$`);

export function isCampaignReadRoute(path, method) {
  return method === "GET" && (content.test(path) || revision.test(path));
}
