import type { APIRoute } from "astro";
import { createHash } from "node:crypto";
import { withEmDashRuntime } from "emdash/middleware";
import {
  PublicCampaignError,
  readPublicCoreCampaign,
} from "../../../../public/core-campaign";
import { readPublishedMedia } from "../../../../public/published-media.mjs";
import { campaignStorage } from "../../../../auth/campaign-media-io.mjs";

const headers = {
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
};
export const GET: APIRoute = async ({ params, request }) => {
  try {
    const slug = params.slug ?? "";
    const id = params.id ?? "";
    const route = await readPublicCoreCampaign(slug);
    if (route.availability !== "published" || !route.action)
      throw new PublicCampaignError(404);
    const actionId = route.action.id;
    const media = await withEmDashRuntime((runtime) =>
      readPublishedMedia(runtime.db, actionId, id),
    );
    if (!media) throw new PublicCampaignError(404);
    const stored = await campaignStorage().download(media.storage_key);
    if (
      !["image/png", "image/jpeg", "image/webp"].includes(media.mime_type) ||
      !/^[0-9a-f]{64}$/.test(media.content_hash ?? "") ||
      stored.contentType !== media.mime_type ||
      createHash("sha256").update(stored.bytes).digest("hex") !==
        media.content_hash
    )
      throw new PublicCampaignError(503);
    // Recheck both authorities AFTER object I/O; a slow download must not
    // preserve a withdrawn Core campaign or an unpublished/replaced reference.
    const current = await readPublicCoreCampaign(slug);
    if (current.availability !== "published" || current.action?.id !== actionId)
      throw new PublicCampaignError(404);
    const confirmed = await withEmDashRuntime((runtime) =>
      readPublishedMedia(runtime.db, actionId, id),
    );
    if (!confirmed) throw new PublicCampaignError(404);
    if (
      confirmed.storage_key !== media.storage_key ||
      confirmed.content_hash !== media.content_hash ||
      confirmed.mime_type !== media.mime_type
    )
      throw new PublicCampaignError(503);
    return new Response(
      request.method === "HEAD" ? null : new Uint8Array(stored.bytes),
      {
        headers: {
          ...headers,
          "Content-Type": media.mime_type,
          "Content-Length": String(stored.size),
          "Content-Disposition": "inline",
          "Content-Security-Policy": "sandbox; default-src 'none'",
        },
      },
    );
  } catch (error) {
    return new Response("Bild nicht verfügbar", {
      status: error instanceof PublicCampaignError ? error.status : 503,
      headers,
    });
  }
};
export const HEAD = GET;
