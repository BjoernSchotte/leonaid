import type { APIRoute } from "astro";
import { listActiveCampaigns } from "../lib/core";
import { hasPublicHost, publicSitemap } from "../lib/site-hosts";

// The public host's sitemap (specs/multi-domain §6.5, §7.5). Campaign hosts
// answer their own /sitemap.xml in the campaign site.
export const GET: APIRoute = async ({ url }) =>
  new Response(
    publicSitemap(url.origin, await listActiveCampaigns(), hasPublicHost()),
    {
      headers: {
        "Content-Type": "application/xml; charset=utf-8",
        "Cache-Control": "public, max-age=300",
      },
    },
  );
