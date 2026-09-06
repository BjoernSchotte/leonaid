import { defineMiddleware } from "astro:middleware";
import {
  readCoreIdentity,
  CoreIdentityError,
  requireCorePublication,
} from "./auth/core-identity";
import {
  isCampaignReadRoute,
  isCampaignUpdateRoute,
  isCampaignRestoreRoute,
  isCampaignDiscardRoute,
  isCampaignPublishRoute,
  isCampaignUnpublishRoute,
} from "./auth/campaign-routes.mjs";
import { authorizeCampaignUpdate } from "./auth/campaign-update.mjs";
import {
  updateCampaignAtomically,
  mutateCampaignAtomically,
} from "./auth/campaign-mutation";
import { requireCampaignBindings } from "./auth/campaign-bindings.mjs";
import {
  listCampaignContent,
  getCampaignContent,
  listCampaignRevisions,
  getCampaignRevision,
  compareCampaignContent,
} from "./auth/campaign-content.mjs";

export const onRequest = defineMiddleware(
  async ({ request, url, locals }, next) => {
    if (
      !isCampaignReadRoute(url.pathname, request.method) &&
      !isCampaignUpdateRoute(url.pathname, request.method) &&
      !isCampaignRestoreRoute(url.pathname, request.method) &&
      !isCampaignDiscardRoute(url.pathname, request.method) &&
      !isCampaignPublishRoute(url.pathname, request.method) &&
      !isCampaignUnpublishRoute(url.pathname, request.method)
    )
      return next();
    try {
      const profile = await readCoreIdentity(request);
      // Positive HTTP proof is System-Admin-only until every operation is scoped.
      const user = locals.user;
      if (profile.role !== 50 || user?.role !== 50)
        throw new CoreIdentityError(403);
      const emdash = locals.emdash;
      if (!emdash?.db) throw new CoreIdentityError(503);
      const database = emdash.db;
      await requireCampaignBindings(database);
      const runtimeGet = emdash.handleContentGet;
      const runtimeUpdate = emdash.handleContentUpdate;
      const runtimeRestore = emdash.handleRevisionRestore;
      const runtimeDiscard = emdash.handleContentDiscardDraft;
      const runtimePublish = emdash.handleContentPublish;
      const runtimeUnpublish = emdash.handleContentUnpublish;
      // EmDash creates this object per request. Never mutate the shared runtime.
      emdash.handleContentList = (collection, parameters) =>
        listCampaignContent(database, profile, collection, parameters);
      emdash.handleContentGet = async (collection, id) => {
        const access = await getCampaignContent(
          database,
          profile,
          collection,
          id,
        );
        if (!access.success) return access;
        // Preserve upstream draft hydration; its lower-level handler reads only
        // the live columns. Binding guards prevent rebinding between these reads.
        const result = await runtimeGet(collection, id);
        if (result.success) {
          const data = result.data?.item.data;
          if (
            !data ||
            typeof data !== "object" ||
            !("action_id" in data) ||
            data.action_id !== access.data.item.data.action_id
          )
            throw new CoreIdentityError(503);
        }
        return result;
      };
      emdash.handleContentUpdate = async (collection, id, body) => {
        const denied = await authorizeCampaignUpdate(
          database,
          profile,
          collection,
          id,
          body,
        );
        // This native runtime flag is omitted from the upstream Locals type.
        // Normalize it explicitly; do not cast away the public handler contract.
        const revisionedBody = { ...body, skipRevision: false };
        return (
          denied ??
          updateCampaignAtomically(
            emdash,
            runtimeUpdate,
            collection,
            id,
            // Native autosave requests may ask to overwrite a draft revision.
            // Retain an attributed revision for every accepted save instead.
            revisionedBody,
            {
              coreUserId: profile.userId,
              cmsUserId: user.id,
            },
          )
        );
      };
      emdash.handleRevisionList = (collection, id, parameters) =>
        listCampaignRevisions(database, profile, collection, id, parameters);
      emdash.handleRevisionGet = (id) =>
        getCampaignRevision(database, profile, id);
      emdash.handleContentCompare = (collection, id) =>
        compareCampaignContent(database, profile, collection, id);
      emdash.handleContentUnpublish = async (collection, id) => {
        const access = await getCampaignContent(
          database,
          profile,
          collection,
          id,
        );
        if (!access.success) return access;
        return mutateCampaignAtomically(
          emdash,
          collection,
          id,
          { coreUserId: profile.userId, cmsUserId: user.id },
          async () => {
            // Withdrawal must remain possible after Core publication is closed.
            const result = await runtimeUnpublish(collection, id);
            // Preserve the existing draft in the response, not stale live columns.
            return result.success ? runtimeGet(collection, id) : result;
          },
          "unpublish",
        );
      };
      emdash.handleContentPublish = async (collection, id, options) => {
        const access = await getCampaignContent(
          database,
          profile,
          collection,
          id,
        );
        if (!access.success) return access;
        if (
          options &&
          Object.values(options).some((value) => value !== undefined)
        )
          throw new CoreIdentityError(403);
        const actionId = access.data.item.data.action_id;
        if (typeof actionId !== "string") throw new CoreIdentityError(503);
        return mutateCampaignAtomically(
          emdash,
          collection,
          id,
          { coreUserId: profile.userId, cmsUserId: user.id },
          async () => {
            await requireCorePublication(request, actionId);
            return runtimePublish(collection, id);
          },
          "publish",
        );
      };
      emdash.handleContentDiscardDraft = async (collection, id) => {
        const access = await getCampaignContent(
          database,
          profile,
          collection,
          id,
        );
        if (!access.success) return access;
        return mutateCampaignAtomically(
          emdash,
          collection,
          id,
          { coreUserId: profile.userId, cmsUserId: user.id },
          () => runtimeDiscard(collection, id),
          "discard-draft",
        );
      };
      emdash.handleRevisionRestore = async (revisionId) => {
        const access = await getCampaignRevision(database, profile, revisionId);
        if (!access.success) return access;
        // Stored parent, not request body or snapshot JSON, selects the lock.
        // The upstream restore creates a NEW draft; it never promotes to live.
        return mutateCampaignAtomically(
          emdash,
          "campaign_pages",
          access.data.item.entryId,
          { coreUserId: profile.userId, cmsUserId: user.id },
          () => runtimeRestore(revisionId, user.id),
        );
      };
      return await next();
    } catch (error) {
      return Response.json(
        { error: { code: "CAMPAIGN_ACCESS_DENIED" } },
        {
          status: error instanceof CoreIdentityError ? error.status : 503,
          headers: { "Cache-Control": "no-store" },
        },
      );
    }
  },
);
