import { LeonAidApiClient } from "@leonaid/api-client";

export class PublicCampaignError extends Error {
  constructor(public readonly status: 404 | 503) {
    super("public_campaign_unavailable");
  }
}

export const campaignSlug = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const client = new LeonAidApiClient("http://api:8000", async (input, init) => {
  // Never forward visitor cookies, authorization, preview flags or a CMS slug.
  const response = await fetch(input, {
    ...init,
    redirect: "error",
    cache: "no-store",
  });
  if (!response.ok) {
    await response.body?.cancel();
    throw new PublicCampaignError(response.status === 404 ? 404 : 503);
  }
  if (!response.headers.get("content-type")?.startsWith("application/json")) {
    await response.body?.cancel();
    throw new PublicCampaignError(503);
  }
  const reader = response.body?.getReader();
  if (!reader) throw new PublicCampaignError(503);
  const chunks: Uint8Array[] = [];
  let bytes = 0;
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      bytes += chunk.value.byteLength;
      if (bytes > 512 * 1024) throw new PublicCampaignError(503);
      chunks.push(chunk.value);
    }
  } finally {
    await reader.cancel();
  }
  return new Response(Buffer.concat(chunks), {
    headers: { "Content-Type": "application/json" },
  });
});

export async function readPublicCoreCampaign(slug: string) {
  if (slug.length > 160 || !campaignSlug.test(slug))
    throw new PublicCampaignError(404);
  try {
    const route = await client.resolvePublicCampaign(slug, {
      signal: AbortSignal.timeout(2000),
    });
    if (
      route.routeKind !== "campaign" ||
      route.routeValue !== slug ||
      route.canonicalPath !== `/campaigns/${slug}/` ||
      !["published", "inactive"].includes(route.availability) ||
      (route.availability === "published" &&
        (!route.action || route.action.archiveSlug !== slug)) ||
      (route.availability === "inactive" &&
        (route.action !== null || route.submissionsAllowed)) ||
      (route.orderAlias !== null &&
        (typeof route.orderAlias !== "string" ||
          !campaignSlug.test(route.orderAlias)))
    )
      throw new PublicCampaignError(503);
    return route;
  } catch (error) {
    if (error instanceof PublicCampaignError) throw error;
    throw new PublicCampaignError(503);
  }
}
