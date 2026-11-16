import type { APIRoute } from "astro";
import { withEmDashRuntime } from "emdash/middleware";
import {
  PublicCampaignError,
  readPublicCoreCampaign,
} from "../../../../public/core-campaign";
import {
  mediaVersion,
  mediaWidths,
  readPublishedMedia,
  versionedMediaCache,
} from "../../../../public/published-media.mjs";
import { publicMediaBytes } from "../../../../public/media-bytes.mjs";

const refusal = {
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
};
// A versioned URL (`?v=` with the content hash) names one file for good: the
// browser keeps it for a year and does not ask again (E-067). Without a
// version the answer is not stored, as before.
export const GET: APIRoute = async ({ params, request, url }) => {
  try {
    const slug = params.slug ?? "";
    const id = params.id ?? "";
    const version = url.searchParams.get("v");
    const widthParameter = url.searchParams.get("w");
    if (
      [...url.searchParams.keys()].some((key) => key !== "v" && key !== "w") ||
      url.searchParams.getAll("v").length > 1 ||
      url.searchParams.getAll("w").length > 1 ||
      (version !== null && !/^[0-9a-f]{16}$/.test(version)) ||
      (widthParameter !== null && version === null)
    )
      throw new PublicCampaignError(404);
    const width = widthParameter === null ? null : Number(widthParameter);
    if (width !== null && !mediaWidths.includes(width))
      throw new PublicCampaignError(404);
    // Both authorities decide on every request: Core says the campaign is
    // public, the CMS says its published page references this file.
    const route = await readPublicCoreCampaign(slug);
    if (route.availability !== "published" || !route.action)
      throw new PublicCampaignError(404);
    const actionId = route.action.id;
    const media = await withEmDashRuntime((runtime) =>
      readPublishedMedia(runtime.db, actionId, id),
    );
    if (!media) throw new PublicCampaignError(404);
    if (version !== null && mediaVersion(media.content_hash) !== version)
      throw new PublicCampaignError(404);
    const file = await publicMediaBytes(media, width);
    return new Response(
      request.method === "HEAD" ? null : new Uint8Array(file.bytes),
      {
        headers: {
          "Cache-Control": version === null ? "no-store" : versionedMediaCache,
          "X-Content-Type-Options": "nosniff",
          "Content-Type": file.contentType,
          "Content-Length": String(file.bytes.length),
          "Content-Disposition": "inline",
          "Content-Security-Policy": "sandbox; default-src 'none'",
        },
      },
    );
  } catch (error) {
    return new Response("Bild nicht verfügbar", {
      status: error instanceof PublicCampaignError ? error.status : 503,
      headers: refusal,
    });
  }
};
export const HEAD = GET;
