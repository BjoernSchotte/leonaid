import { defineMiddleware } from "astro:middleware";
import { cmsMaintenanceClosed } from "./cms-maintenance.mjs";
import { withEmDashRuntime } from "emdash/middleware";
import {
  PublicCampaignError,
  readPublicCoreCampaign,
} from "./public/core-campaign";
import { readPublishedCampaign } from "./public/published-campaign.mjs";
import { databaseReady, setupIsComplete } from "./database-ready";
import { authenticate } from "./auth/leonaid-auth";
import {
  CoreIdentityError,
  requireCurrentCampaignActor,
} from "./auth/core-identity";
import { campaignManifest } from "./auth/campaign-manifest.mjs";
import { campaignMediaRoute } from "./auth/campaign-media-routes.mjs";
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
export const onRequest = defineMiddleware(
  async ({ url, request, cookies }, next) => {
    const headers = { "Cache-Control": "no-store" };
    if (url.pathname === "/health/live") {
      return new Response("ok", { headers });
    }
    if (await cmsMaintenanceClosed()) {
      return new Response("CMS temporarily unavailable", {
        status: 503,
        headers: { ...headers, "Retry-After": "60" },
      });
    }
    if (url.pathname === "/health/ready") {
      const ready = await databaseReady();
      return new Response(ready ? "ok" : "unavailable", {
        status: ready ? 200 : 503,
        headers,
      });
    }
    if (
      /^\/campaigns\/[a-z0-9]+(?:-[a-z0-9]+)*(?:\/media\/[0-9A-HJKMNP-TV-Z]{26})?\/?$/.test(
        url.pathname,
      )
    ) {
      // Public paths never enter EmDash's native preview/edit-mode hydration.
      // A separately authorized preview flow remains a later acceptance gate.
      if (
        url.searchParams.has("_preview") ||
        cookies.get("emdash-edit-mode")?.value === "true"
      )
        return new Response("Preview is not available on this public route", {
          status: 403,
          headers,
        });
      const nativeOrderPost =
        request.method === "POST" &&
        /^\/campaigns\/[a-z0-9]+(?:-[a-z0-9]+)*\/$/.test(url.pathname) &&
        url.searchParams.size === 1 &&
        url.searchParams.get("_action") === "createPublicOrder";
      if (!["GET", "HEAD"].includes(request.method) && !nativeOrderPost)
        return new Response("Method not allowed", {
          status: 405,
          headers: { ...headers, Allow: "GET, HEAD" },
        });
      try {
        if (!hasSecurePublicOrigin(request))
          return new Response("Invalid CMS origin", { status: 403, headers });
        await requireCompletedBootstrap(bootstrapDirectory);
        if (!(await setupIsComplete())) throw new Error();
        if (nativeOrderPost) {
          // Astro executes actions below the user middleware chain. Admit only
          // a currently published canonical page before invoking the shared
          // order action; Core still validates its alias, token and order data.
          const route = await readPublicCoreCampaign(
            url.pathname.split("/")[2],
          );
          if (
            !route.submissionsAllowed ||
            !route.orderAlias ||
            !route.action?.orderForm ||
            !(await withEmDashRuntime((runtime) =>
              readPublishedCampaign(runtime.db, route.action!.id),
            ))
          )
            return new Response("Bestellung derzeit nicht verfügbar", {
              status: 404,
              headers,
            });
        }
        const response = await next();
        response.headers.set("Cache-Control", "no-store");
        return response;
      } catch (error) {
        if (error instanceof PublicCampaignError && error.status === 404)
          return new Response("Aktionsseite nicht verfügbar", {
            status: 404,
            headers,
          });
        console.warn("public_campaign_pipeline_unavailable");
        return new Response("Aktionsseite vorübergehend nicht erreichbar", {
          status: 503,
          headers,
        });
      }
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
        if (identity.role !== 50) throw new CoreIdentityError(403);
        await requireArmedBootstrap(bootstrapDirectory, identity.subject);
        if (!hasSecurePublicOrigin(request))
          return new Response("Invalid CMS origin", { status: 403, headers });
        if (await setupIsComplete()) throw new Error();
        if (setupPost) {
          if (request.headers.get("X-EmDash-Request") !== "1")
            return new Response("Invalid CMS request", {
              status: 403,
              headers,
            });
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
      Boolean(campaignMediaRoute(url.pathname, request.method)) ||
      isCampaignReadRoute(url.pathname, request.method) ||
      ["/_emdash/api/manifest", "/_emdash/api/dashboard"].includes(
        url.pathname,
      );
    const campaignUpdate =
      (Boolean(campaignMediaRoute(url.pathname, request.method)) &&
        request.method !== "GET") ||
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
        if (identity.role === 40) {
          if (url.pathname === "/_emdash/api/dashboard")
            throw new CoreIdentityError(403);
          if (adminHome)
            return new Response(null, {
              status: 303,
              headers: {
                ...headers,
                Location: "/_emdash/admin/content/campaign_pages",
              },
            });
          if (url.pathname === "/_emdash/api/manifest")
            return Response.json(
              { success: true, data: campaignManifest() },
              { headers },
            );
          if (campaignNew && !campaignHandoff) throw new CoreIdentityError(403);
        }
        if (campaignNew && campaignParameters.length) {
          if (!campaignHandoff) throw new CoreIdentityError(403);
          await requireCurrentCampaignActor(
            request,
            {
              coreUserId: identity.subject,
              coreRole: identity.role,
            },
            campaignHandoff,
          );
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
  },
);
