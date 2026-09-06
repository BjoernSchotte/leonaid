import { defineMiddleware } from "astro:middleware";
import { databaseReady } from "./database-ready";
import { authenticate } from "./auth/leonaid-auth";
import { CoreIdentityError } from "./auth/core-identity";

// Intentionally no enable environment variable. Broader access requires the
// EMS-020/070 gates; only verified read-only identity reaches a CMS handler.
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
  // First integrated read-only seam. Editor, mutations, setup and alternative
  // credentials remain closed until their own acceptance gates pass.
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
