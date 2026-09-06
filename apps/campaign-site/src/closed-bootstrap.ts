import { defineMiddleware } from "astro:middleware";
import { databaseReady, setupIsComplete } from "./database-ready";
import { authenticate } from "./auth/leonaid-auth";
import { CoreIdentityError, requireCoreCampaign } from "./auth/core-identity";
import { hasSecurePublicOrigin } from "./auth/public-origin";
import {
  isCampaignEditorRoute,
  isCampaignCreateRoute,
  isCampaignReadRoute,
  isCampaignUpdateRoute,
  isCampaignRestoreRoute,
  isCampaignDiscardRoute,
  isCampaignPublishRoute,
  isCampaignUnpublishRoute,
} from "./auth/campaign-routes.mjs";
import {
  bootstrapIsArmed,
  requireArmedBootstrap,
  consumeBootstrap,
  completeBootstrap,
  requireCompletedBootstrap,
} from "./bootstrap-control.mjs";

const bootstrapDirectory = "/app/bootstrap-state";

// Intentionally no enable environment variable. Broader access requires the
// EMS-020/070 gates; setup additionally needs an explicit one-time operator grant.
export const onRequest = defineMiddleware(async ({ url, request }, next) => {
  const headers = { "Cache-Control": "no-store" };
  if (url.pathname === "/health/live") {
    return new Response("ok", { headers });
  }
  if (url.pathname === "/health/ready") {
    const ready = await databaseReady();
    return new Response(ready ? "ok" : "unavailable", {
      status: ready ? 200 : 503,
      headers,
    });
  }
  const setupPage =
    url.pathname === "/_emdash/admin/setup" ||
    url.pathname === "/_emdash/admin/setup/";
  const setupStatus = url.pathname === "/_emdash/api/setup/status";
  const setupPost =
    url.pathname === "/_emdash/api/setup" && request.method === "POST";
  if (((setupPage || setupStatus) && request.method === "GET") || setupPost) {
    if (!(await bootstrapIsArmed(bootstrapDirectory)))
      return new Response("CMS access is not enabled", {
        status: 503,
        headers,
      });
    try {
      if (import.meta.env.DEV || request.headers.has("Authorization"))
        throw new Error();
      const identity = await authenticate(request);
      await requireArmedBootstrap(bootstrapDirectory, identity.subject);
      if (!hasSecurePublicOrigin(request))
        return new Response("Invalid CMS origin", { status: 403, headers });
      if (await setupIsComplete()) throw new Error();
      if (setupPost) {
        if (request.headers.get("X-EmDash-Request") !== "1")
          return new Response("Invalid CMS request", { status: 403, headers });
        // Consume BEFORE upstream mutation. Failure/crash cannot reopen setup.
        await consumeBootstrap(bootstrapDirectory, identity.subject);
      }
      const response = await next();
      if (setupPost) {
        // Upstream can report success despite failing to save completion.
        if (!response.ok || !(await setupIsComplete())) throw new Error();
        await completeBootstrap(bootstrapDirectory, identity.subject);
      }
      response.headers.set("Cache-Control", "no-store");
      return response;
    } catch (error) {
      const status = error instanceof CoreIdentityError ? error.status : 503;
      return Response.json(
        { error: { code: "CMS_SETUP_DENIED" } },
        { status, headers },
      );
    }
  }
  const adminHome =
    url.pathname === "/_emdash/admin" || url.pathname === "/_emdash/admin/";
  const adminPage =
    adminHome || isCampaignEditorRoute(url.pathname, request.method);
  const campaignNew =
    /^\/_emdash\/admin\/content\/campaign_pages\/new\/?$/.test(url.pathname);
  const campaignParameters = url.searchParams.getAll("campaign");
  const campaignHandoff =
    campaignNew &&
    campaignParameters.length === 1 &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
      campaignParameters[0],
    )
      ? campaignParameters[0]
      : null;
  const adminRead =
    isCampaignReadRoute(url.pathname, request.method) ||
    ["/_emdash/api/manifest", "/_emdash/api/dashboard"].includes(url.pathname);
  const campaignUpdate =
    isCampaignCreateRoute(url.pathname, request.method) ||
    isCampaignUpdateRoute(url.pathname, request.method) ||
    isCampaignRestoreRoute(url.pathname, request.method) ||
    isCampaignDiscardRoute(url.pathname, request.method) ||
    isCampaignPublishRoute(url.pathname, request.method) ||
    isCampaignUnpublishRoute(url.pathname, request.method);
  // Upstream permits only the current user's dismissWelcome preference here.
  // It does not edit identity, role, credentials or another user's profile.
  const dismissWelcome =
    url.pathname === "/_emdash/api/auth/me" && request.method === "POST";
  if (
    ((adminPage || adminRead) && request.method === "GET") ||
    campaignUpdate ||
    dismissWelcome
  ) {
    try {
      if (import.meta.env.DEV || request.headers.has("Authorization"))
        throw new Error();
      // A manifest is needed by the setup SPA, but only its designated actor
      // may obtain it before completion. All other reads require both stores.
      const setupManifest =
        url.pathname === "/_emdash/api/manifest" &&
        (await bootstrapIsArmed(bootstrapDirectory));
      if (!setupManifest) await requireCompletedBootstrap(bootstrapDirectory);
      if (!hasSecurePublicOrigin(request))
        return new Response("Invalid CMS origin", { status: 403, headers });
      if (
        (campaignUpdate || dismissWelcome) &&
        request.headers.get("X-EmDash-Request") !== "1"
      )
        return new Response("Invalid CMS request", { status: 403, headers });
      const identity = await authenticate(request);
      if (campaignNew && campaignParameters.length) {
        if (!campaignHandoff) throw new CoreIdentityError(403);
        await requireCoreCampaign(request, campaignHandoff);
      }
      if (setupManifest)
        await requireArmedBootstrap(bootstrapDirectory, identity.subject);
      else if (!(await setupIsComplete())) throw new Error();
      const response = await next();
      response.headers.set("Cache-Control", "no-store");
      return response;
    } catch (error) {
      const status = error instanceof CoreIdentityError ? error.status : 503;
      if (adminPage && status === 401) {
        return new Response(null, {
          status: 303,
          headers: {
            ...headers,
            Location: `/login?returnTo=${encodeURIComponent(adminHome ? "/_emdash/admin/" : url.pathname + (campaignHandoff ? `?campaign=${campaignHandoff}` : ""))}`,
          },
        });
      }
      if (!(error instanceof CoreIdentityError))
        return new Response("CMS access is not enabled", {
          status: 503,
          headers,
        });
      return Response.json(
        { error: { code: "CMS_ADMIN_DENIED" } },
        { status, headers },
      );
    }
  }
  // Editor and non-setup mutations remain closed until their acceptance gates.
  if (url.pathname === "/_emdash/api/auth/me" && request.method === "GET") {
    // Upstream development and bearer paths bypass external auth. Never enter
    // either path, even when a valid Core cookie accompanies another credential.
    if (import.meta.env.DEV || request.headers.has("Authorization")) {
      return Response.json(
        { error: { code: "ALTERNATIVE_AUTH_DISABLED" } },
        { status: 403, headers },
      );
    }
    try {
      await authenticate(request);
      const response = await next();
      response.headers.set("Cache-Control", "no-store");
      return response;
    } catch (error) {
      const status = error instanceof CoreIdentityError ? error.status : 503;
      return Response.json(
        { error: { code: "CORE_IDENTITY_DENIED" } },
        { status, headers },
      );
    }
  }
  return new Response("CMS access is not enabled", { status: 503, headers });
});
