import { defineMiddleware } from "astro:middleware";
import { readCoreIdentity, CoreIdentityError } from "./auth/core-identity";
import { isCampaignReadRoute } from "./auth/campaign-routes.mjs";
import { requireCampaignBindings } from "./auth/campaign-bindings.mjs";
import {
  listCampaignContent,
  getCampaignContent,
  listCampaignRevisions,
  getCampaignRevision,
} from "./auth/campaign-content.mjs";

export const onRequest = defineMiddleware(
  async ({ request, url, locals }, next) => {
    if (!isCampaignReadRoute(url.pathname, request.method)) return next();
    try {
      const profile = await readCoreIdentity(request);
      // Positive HTTP proof is System-Admin-only until every operation is scoped.
      if (profile.role !== 50 || locals.user?.role !== 50)
        throw new CoreIdentityError(403);
      const emdash = locals.emdash;
      if (!emdash?.db) throw new CoreIdentityError(503);
      const database = emdash.db;
      await requireCampaignBindings(database);
      // EmDash creates this object per request. Never mutate the shared runtime.
      emdash.handleContentList = (collection, parameters) =>
        listCampaignContent(database, profile, collection, parameters);
      emdash.handleContentGet = (collection, id) =>
        getCampaignContent(database, profile, collection, id);
      emdash.handleRevisionList = (collection, id, parameters) =>
        listCampaignRevisions(database, profile, collection, id, parameters);
      emdash.handleRevisionGet = (id) =>
        getCampaignRevision(database, profile, id);
      return await next();
    } catch (error) {
      return Response.json(
        { error: { code: "CAMPAIGN_READ_DENIED" } },
        {
          status: error instanceof CoreIdentityError ? error.status : 503,
          headers: { "Cache-Control": "no-store" },
        },
      );
    }
  },
);
