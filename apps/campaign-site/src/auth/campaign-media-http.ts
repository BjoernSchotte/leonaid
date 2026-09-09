import type { APIContext } from "astro";
import { z } from "astro/zod";
import { createHash } from "node:crypto";
import { sql } from "kysely";
import { MediaRepository } from "emdash";
import {
  CoreIdentityError,
  readCoreIdentity,
  requireCurrentCampaignActor,
} from "./core-identity";
import {
  campaignMediaRoute,
  campaignMediaFileKey,
} from "./campaign-media-routes.mjs";
import {
  CampaignMediaError,
  campaignStorage,
  readCampaignBytes,
} from "./campaign-media-io.mjs";
import {
  createCampaignPendingMedia,
  getCampaignMedia,
  listCampaignMedia,
  requireCampaignMedia,
  resolveCampaignMedia,
} from "./campaign-media.mjs";
import { stageCampaignImageUpload } from "./campaign-media-upload.mjs";
import {
  campaignImageMaxBytes,
  normalizeCampaignImage,
} from "./campaign-image.mjs";

const reservation = z
  .object({
    filename: z.string().min(1).max(200),
    contentType: z.enum(["image/png", "image/jpeg", "image/webp"]),
    size: z.number().int().min(1).max(campaignImageMaxBytes),
    // Native clients compute SHA-1; never use it for cross-campaign deduplication
    // or as evidence that the actual stored bytes have passed validation.
    contentHash: z
      .string()
      .regex(/^sha1:[0-9a-f]{40}$/)
      .optional(),
    fieldId: z.string().min(1).max(100).optional(),
    deduplicate: z.literal(false).optional(),
  })
  .strict();
const confirmation = z
  .object({
    size: z.number().int().min(1).max(campaignImageMaxBytes).optional(),
    width: z.number().int().min(1).max(8192).optional(),
    height: z.number().int().min(1).max(8192).optional(),
  })
  .strict();
const headers = { "Cache-Control": "no-store" };
const success = (data: unknown, status = 200) =>
  Response.json({ success: true, data }, { status, headers });
const withUrl = (item: { storageKey: string }) => ({
  ...item,
  url: `/_emdash/api/media/file/${item.storageKey}`,
});
async function jsonBody(request: Request) {
  if (!request.headers.get("content-type")?.startsWith("application/json"))
    throw new CampaignMediaError(400, "MEDIA_BODY_INVALID");
  try {
    return JSON.parse(
      (await readCampaignBytes(request.body, 4096)).toString("utf8"),
    );
  } catch (error) {
    if (error instanceof CampaignMediaError) throw error;
    throw new CampaignMediaError(400, "MEDIA_BODY_INVALID");
  }
}

// Intercepts only the explicitly admitted native protocol routes. The original
// global handlers are never invoked, including global hash/media-usage lookups.
export async function campaignMediaHttp({ request, url, locals }: APIContext) {
  try {
    const route = campaignMediaRoute(url.pathname, request.method);
    if (!route) throw new CampaignMediaError(403, "MEDIA_ACCESS_DENIED");
    const profile = await readCoreIdentity(request);
    const user = locals.user;
    // Upstream intentionally skips auth for its public file route. Our file
    // handler instead requires fresh Core authority and a scoped media lookup;
    // it must neither trust nor require an independent Astro/CMS session.
    if (
      ![40, 50].includes(profile.role) ||
      (route !== "file" && user?.role !== profile.role)
    )
      throw new CoreIdentityError(403);
    const database = locals.emdash.db;
    await requireCampaignMedia(database);
    let id = url.pathname.split("/")[4];
    let actionId: string;
    if (route === "list" || route === "reserve") {
      const campaigns = url.searchParams.getAll("campaign");
      if (
        campaigns.length !== 1 ||
        !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
          campaigns[0],
        )
      )
        throw new CampaignMediaError(403, "MEDIA_ACCESS_DENIED");
      actionId = campaigns[0];
      const allowed =
        route === "list"
          ? ["campaign", "limit", "cursor", "q", "mimeType"]
          : ["campaign"];
      if (
        [...url.searchParams.keys()].some(
          (key) =>
            !allowed.includes(key) || url.searchParams.getAll(key).length !== 1,
        )
      )
        throw new CampaignMediaError(400, "MEDIA_QUERY_INVALID");
    } else {
      if (url.search) throw new CampaignMediaError(400, "MEDIA_QUERY_INVALID");
      const binding = await resolveCampaignMedia(
        database,
        profile,
        route === "file" ? { key: campaignMediaFileKey(url.pathname) } : { id },
      );
      if (!binding) throw new CampaignMediaError(404, "MEDIA_NOT_FOUND");
      actionId = binding.action_id;
      id = binding.id;
    }
    const actor = { coreUserId: profile.userId, coreRole: profile.role };
    await requireCurrentCampaignActor(request, actor, actionId);
    const beforeWrite = async (transaction: typeof database) => {
      if (!user) throw new CoreIdentityError(403);
      const mapping =
        await sql`SELECT cms_user_id FROM public.leonaid_external_identity
        WHERE core_user_id=${profile.userId} AND cms_user_id=${user.id}`.execute(
          transaction,
        );
      if (mapping.rows.length !== 1) throw new CoreIdentityError(503);
      await requireCurrentCampaignActor(request, actor, actionId);
    };
    if (route === "list") {
      const result = await listCampaignMedia(database, profile, actionId, {
        ...(url.searchParams.has("limit")
          ? { limit: Number(url.searchParams.get("limit")) }
          : {}),
        ...(url.searchParams.has("cursor")
          ? { cursor: url.searchParams.get("cursor") }
          : {}),
        ...(url.searchParams.has("q") ? { q: url.searchParams.get("q") } : {}),
        ...(url.searchParams.has("mimeType")
          ? { mimeType: url.searchParams.get("mimeType") }
          : {}),
      });
      return success({ ...result, items: result.items.map(withUrl) });
    }
    if (route === "reserve") {
      if (!user) throw new CoreIdentityError(403);
      const parsed = reservation.safeParse(await jsonBody(request));
      if (!parsed.success)
        throw new CampaignMediaError(400, "MEDIA_BODY_INVALID");
      const item = await createCampaignPendingMedia(
        database,
        profile,
        actionId,
        {
          filename: parsed.data.filename,
          mimeType: parsed.data.contentType,
          size: parsed.data.size,
          authorId: user.id,
        },
        beforeWrite,
      );
      return success({
        uploadUrl: `/_emdash/api/media/${item.id}/upload`,
        method: "PUT",
        headers: { "Content-Type": item.mimeType, "X-EmDash-Request": "1" },
        mediaId: item.id,
        storageKey: item.storageKey,
        expiresAt: new Date(
          Date.parse(item.createdAt) + 15 * 60_000,
        ).toISOString(),
      });
    }
    const item = await getCampaignMedia(database, profile, actionId, id);
    if (!item) throw new CampaignMediaError(404, "MEDIA_NOT_FOUND");
    if (route === "get") return success({ item: withUrl(item) });
    if (
      item.status === "pending" &&
      Date.parse(item.createdAt) + 15 * 60_000 <= Date.now()
    )
      throw new CampaignMediaError(409, "MEDIA_UPLOAD_EXPIRED");
    if (route === "upload") {
      if (item.status !== "pending")
        throw new CampaignMediaError(409, "MEDIA_UPLOAD_CONFLICT");
      const length = request.headers.get("content-length");
      if (
        length !== null &&
        (!/^\d+$/.test(length) || Number(length) !== item.size)
      )
        throw new CampaignMediaError(
          Number(length) > campaignImageMaxBytes ? 413 : 400,
          "MEDIA_BODY_INVALID",
        );
      const bytes = await readCampaignBytes(
        request.body,
        campaignImageMaxBytes,
      );
      return success(
        await stageCampaignImageUpload(
          database,
          campaignStorage(),
          profile,
          actionId,
          id,
          bytes,
          request.headers.get("content-type"),
          beforeWrite,
        ),
      );
    }
    if (route === "file" && item.status !== "ready")
      throw new CampaignMediaError(404, "MEDIA_NOT_FOUND");
    if (route === "confirm") {
      const body = confirmation.safeParse(await jsonBody(request));
      if (
        !body.success ||
        (item.status === "pending" &&
          body.data.size !== undefined &&
          body.data.size !== item.size)
      )
        throw new CampaignMediaError(400, "MEDIA_BODY_INVALID");
    }
    if (!/^[0-9a-f]{64}$/.test(item.contentHash ?? ""))
      throw new CampaignMediaError(409, "MEDIA_UPLOAD_INCOMPLETE");
    const stored = await campaignStorage().download(item.storageKey);
    if (
      stored.contentType !== item.mimeType ||
      createHash("sha256").update(stored.bytes).digest("hex") !==
        item.contentHash
    )
      throw new CampaignMediaError(503, "MEDIA_STORAGE_UNAVAILABLE");
    if (route === "file") {
      // Private editorial preview only. Public published-media delivery has a
      // separate publication/reference gate and is not enabled by this endpoint.
      await requireCurrentCampaignActor(request, actor, actionId);
      return new Response(new Uint8Array(stored.bytes), {
        headers: {
          ...headers,
          "Content-Type": item.mimeType,
          "Content-Length": String(stored.size),
          "Content-Disposition": "inline",
          "X-Content-Type-Options": "nosniff",
          "Content-Security-Policy": "sandbox; default-src 'none'",
        },
      });
    }
    const decoded = await normalizeCampaignImage(stored.bytes, item.mimeType);
    const confirmed = await database
      .transaction()
      .execute(async (transaction) => {
        await sql`SET LOCAL lock_timeout = '2s'`.execute(transaction);
        await sql`SET LOCAL statement_timeout = '3s'`.execute(transaction);
        await requireCampaignMedia(transaction);
        const current = await sql<{
          storage_key: string;
          content_hash: string;
          status: string;
        }>`
        SELECT m.storage_key, m.content_hash, m.status FROM public.media m
        JOIN public.leonaid_campaign_media b ON b.media_id=m.id
        WHERE m.id=${id} AND b.action_id=${actionId} FOR UPDATE`.execute(
          transaction,
        );
        if (
          current.rows.length !== 1 ||
          current.rows[0].storage_key !== item.storageKey ||
          current.rows[0].content_hash !== item.contentHash
        )
          throw new CampaignMediaError(409, "MEDIA_UPLOAD_CONFLICT");
        await beforeWrite(transaction);
        const repository = new MediaRepository(transaction);
        if (current.rows[0].status === "ready") return repository.findById(id);
        if (
          current.rows[0].status !== "pending" ||
          !(await repository.hasUploadAttempt(item.storageKey))
        )
          throw new CampaignMediaError(409, "MEDIA_UPLOAD_INCOMPLETE");
        const ready = await repository.confirmUpload(
          id,
          {
            size: stored.size,
            width: decoded.width,
            height: decoded.height,
            contentHash: item.contentHash,
          },
          item.storageKey,
        );
        if (!ready) throw new CampaignMediaError(409, "MEDIA_UPLOAD_CONFLICT");
        await repository.deleteUploadAttempt(item.storageKey);
        return ready;
      });
    if (!confirmed) throw new CampaignMediaError(409, "MEDIA_UPLOAD_CONFLICT");
    return success({ item: withUrl(confirmed) });
  } catch (error) {
    const known: Record<string, number> = {
      campaign_image_invalid: 400,
      campaign_image_busy: 429,
      campaign_media_input_invalid: 400,
      campaign_media_access_denied: 403,
      campaign_media_not_found: 404,
      campaign_media_upload_conflict: 409,
    };
    const status =
      error instanceof CoreIdentityError || error instanceof CampaignMediaError
        ? error.status
        : (known[error instanceof Error ? error.message : ""] ?? 503);
    return Response.json(
      {
        success: false,
        error: {
          code: status === 404 ? "MEDIA_NOT_FOUND" : "MEDIA_REQUEST_DENIED",
          message: "Media request denied",
        },
      },
      { status, headers },
    );
  }
}
