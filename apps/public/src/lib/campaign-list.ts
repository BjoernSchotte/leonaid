import type { PublicCampaignListItemResponse } from "@leonaid/api-client";

/**
 * Active campaigns of the home page (specs/multi-domain §6.5), cached per
 * process like the legal notice: the home page is the most visited page and
 * the list changes only with a publication window.
 * - a list for 60 s (the Core response says `max-age=60`);
 * - a failed read for 10 s: renders do not each wait for the timeout, and a
 *   failure keeps serving the last known list, but only while it is at most
 *   15 minutes old: a longer Core outage must not keep showing campaigns
 *   whose publication window has closed since.
 * One request is shared by concurrent renders.
 */
const listMilliseconds = 60_000;
const failureMilliseconds = 10_000;
export const lastKnownMaxAgeMilliseconds = 15 * 60_000;

type Campaigns = readonly PublicCampaignListItemResponse[];
type LoadCampaigns = () => Promise<Campaigns>;

export function createCampaignListReader(
  load: LoadCampaigns,
  clock: () => number = Date.now,
) {
  let cached: { campaigns: Campaigns; until: number } | null = null;
  let lastKnown: { campaigns: Campaigns; loadedAt: number } | null = null;
  let pending: Promise<Campaigns> | null = null;

  async function refresh(): Promise<Campaigns> {
    try {
      const campaigns = await load();
      lastKnown = { campaigns, loadedAt: clock() };
      cached = { campaigns, until: clock() + listMilliseconds };
    } catch {
      console.warn("public_campaign_list_unavailable");
      const fresh =
        lastKnown !== null &&
        clock() - lastKnown.loadedAt <= lastKnownMaxAgeMilliseconds;
      cached = {
        campaigns: fresh && lastKnown ? lastKnown.campaigns : [],
        until: clock() + failureMilliseconds,
      };
    }
    return cached.campaigns;
  }

  return async function read(): Promise<Campaigns> {
    if (cached && cached.until > clock()) return cached.campaigns;
    pending ??= refresh().finally(() => {
      pending = null;
    });
    return pending;
  };
}
