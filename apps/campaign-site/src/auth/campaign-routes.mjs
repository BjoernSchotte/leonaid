// Only these proven read handlers may pass the outer default-deny boundary.
// IDs are canonical EmDash ULIDs; public slugs are resolved separately by Core.
const id = "[0-9A-HJKMNP-TV-Z]{26}";
const editor = new RegExp(
  `^/_emdash/admin/content/campaign_pages(?:/(?:${id}|new))?/?$`,
);
export function isCampaignEditorRoute(path, method) {
  return method === "GET" && (editor.test(path) || handoff.test(path));
}

const handoff =
  /^\/_emdash\/admin\/campaigns\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/?$/;

export function isCampaignCreateRoute(path, method) {
  return method === "POST" && path === "/_emdash/api/content/campaign_pages";
}

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

const publish = new RegExp(
  `^/_emdash/api/content/campaign_pages/${id}/publish$`,
);
export function isCampaignPublishRoute(path, method) {
  return method === "POST" && publish.test(path);
}

const unpublish = new RegExp(
  `^/_emdash/api/content/campaign_pages/${id}/unpublish$`,
);
export function isCampaignUnpublishRoute(path, method) {
  return method === "POST" && unpublish.test(path);
}
