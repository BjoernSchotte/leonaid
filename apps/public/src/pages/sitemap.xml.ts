import type { APIRoute } from "astro";
import { listActiveCampaigns } from "../lib/core";
import { hasPublicHost, publicSitemap } from "../lib/site-hosts";

// A crawler request must not wait for a slow or absent Core: after this
// bound the sitemap lists the home page only and is not cached.
const CAMPAIGN_LIST_WAIT_MILLISECONDS = 1_500;

// The public host's sitemap (specs/multi-domain §6.5, §7.5). Campaign hosts
// answer their own /sitemap.xml in the campaign site.
export const GET: APIRoute = async ({ url }) => {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const campaigns = await Promise.race([
    listActiveCampaigns().catch(() => null),
    new Promise<null>((resolve) => {
      timer = setTimeout(() => resolve(null), CAMPAIGN_LIST_WAIT_MILLISECONDS);
    }),
  ]);
  clearTimeout(timer);
  return new Response(
    publicSitemap(url.origin, campaigns ?? [], hasPublicHost()),
    {
      headers: {
        "Content-Type": "application/xml; charset=utf-8",
        "Cache-Control": campaigns ? "public, max-age=300" : "no-store",
      },
    },
  );
};
