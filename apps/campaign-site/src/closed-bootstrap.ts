import { defineMiddleware } from "astro:middleware";

// Intentionally no enable environment variable. Replace only after EMS-020/070
// prove Core authentication and protected bootstrap. No CMS handler runs yet.
export const onRequest = defineMiddleware(({ url }) => {
  const headers = { "Cache-Control": "no-store" };
  if (url.pathname === "/health/live") {
    return new Response("ok", { headers });
  }
  return new Response("CMS access is not enabled", { status: 503, headers });
});
