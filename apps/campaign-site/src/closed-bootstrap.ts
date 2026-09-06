import { defineMiddleware } from "astro:middleware";
import { databaseReady } from "./database-ready";

// Intentionally no enable environment variable. Replace only after EMS-020/070
// prove Core authentication and protected bootstrap. No CMS handler runs yet.
export const onRequest = defineMiddleware(async ({ url }) => {
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
  return new Response("CMS access is not enabled", { status: 503, headers });
});
