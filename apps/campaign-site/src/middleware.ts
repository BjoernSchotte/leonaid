import { defineMiddleware } from "astro:middleware";
import { readCoreIdentity, CoreIdentityError } from "./auth/core-identity";
import {
  isCampaignReadRoute,
  isCampaignUpdateRoute,
} from "./auth/campaign-routes.mjs";
import { authorizeCampaignUpdate } from "./auth/campaign-update.mjs";
import { updateCampaignAtomically } from "./auth/campaign-mutation";
import { requireCampaignBindings } from "./auth/campaign-bindings.mjs";
import {
  listCampaignContent,
  getCampaignContent,
  listCampaignRevisions,
  getCampaignRevision,
} from "./auth/campaign-content.mjs";

export const onRequest = defineMiddleware(
  async ({ request, url, locals }, next) => {
    if (
      !isCampaignReadRoute(url.pathname, request.method) &&
      !isCampaignUpdateRoute(url.pathname, request.method)
    )
      return next();
    try {
      const profile = await readCoreIdentity(request);
      // Positive HTTP proof is System-Admin-only until every operation is scoped.
      if (profile.role !== 50 || locals.user?.role !== 50)
        throw new CoreIdentityError(403);
      const emdash = locals.emdash;
      if (!emdash?.db) throw new CoreIdentityError(503);
      const database = emdash.db;
      await requireCampaignBindings(database);
      const runtimeGet = emdash.handleContentGet;
      const runtimeUpdate = emdash.handleContentUpdate;
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
        return (
          denied ??
          updateCampaignAtomically(emdash, runtimeUpdate, collection, id, body)
        );
      };
      emdash.handleRevisionList = (collection, id, parameters) =>
        listCampaignRevisions(database, profile, collection, id, parameters);
      emdash.handleRevisionGet = (id) =>
        getCampaignRevision(database, profile, id);
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
