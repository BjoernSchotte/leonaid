import type { RailCampaign } from "@leonaid/ui";

/** Per-tab memory of the campaign the admin chose in the rail switcher. */
export const CAMPAIGN_STORAGE_KEY = "leonaid.admin.campaign";

/** Admin areas whose pages read the campaign from `?action=`. */
export const CAMPAIGN_SCOPED_NAV_KEYS: ReadonlySet<string> = new Set([
  "overview-web",
  "orders",
  "invoices",
  "donations",
  "acquisition-web",
]);

export function readStoredCampaign(): string {
  try {
    return window.sessionStorage.getItem(CAMPAIGN_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function storeCampaign(actionId: string): void {
  try {
    window.sessionStorage.setItem(CAMPAIGN_STORAGE_KEY, actionId);
  } catch {
    // Without storage the choice still travels in the links of this page.
  }
}

/** `href` with `?action=<actionId>`; other query parameters stay. */
export function withCampaign(href: string, actionId: string): string {
  if (!actionId || !href.startsWith("/")) return href;
  const url = new URL(href, "https://leonaid.invalid");
  url.searchParams.set("action", actionId);
  return `${url.pathname}${url.search}${url.hash}`;
}

export interface CampaignSelectionInput {
  readonly campaigns: readonly RailCampaign[];
  /** The page reads its campaign from the URL (dashboard, orders, …). */
  readonly scoped: boolean;
  /** A campaign's own management page: its id is the selection. */
  readonly managedActionId?: string;
  readonly urlActionId: string;
  readonly storedActionId: string;
  /** Preferred first choice, e.g. the first campaign the account manages. */
  readonly fallbackActionId?: string;
}

/**
 * The campaign the rail shows. The URL wins on pages that read it; the
 * stored choice holds across pages that do not; ids the account cannot use
 * on the admin pages never win. "" when nothing fits (a management page of
 * a campaign the account is not a member of).
 */
export function selectCampaign({
  campaigns,
  scoped,
  managedActionId,
  urlActionId,
  storedActionId,
  fallbackActionId,
}: CampaignSelectionInput): string {
  const usable = (id: string | undefined): id is string =>
    Boolean(id) && campaigns.some((campaign) => campaign.id === id);
  if (managedActionId !== undefined) {
    return usable(managedActionId) ? managedActionId : "";
  }
  if (scoped && usable(urlActionId)) return urlActionId;
  if (usable(storedActionId)) return storedActionId;
  if (usable(fallbackActionId)) return fallbackActionId;
  return campaigns[0]?.id ?? "";
}
