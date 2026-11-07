import { defineMiddleware } from "astro:middleware";
import { isActiveSiteHost } from "./lib/core";
import { guardOrderBody, isOrderSubmission } from "./lib/order-body";
import { campaignHostname, configuredHostnames } from "./lib/site-hosts";

const configured = configuredHostnames();

export const onRequest = defineMiddleware(async ({ request, url }, next) => {
  // A name that is not one of this installation's hosts is a campaign host:
  // served only while Core returns it as active (specs/multi-domain §9.2).
  if (!url.pathname.startsWith("/health/")) {
    const hostname = campaignHostname(request.headers.get("host"), configured);
    if (hostname !== null) {
      let active = false;
      try {
        active = await isActiveSiteHost(hostname);
      } catch {
        return new Response("Vorübergehend nicht erreichbar", {
          status: 503,
          headers: { "Cache-Control": "no-store", "Retry-After": "30" },
        });
      }
      if (!active)
        return new Response("Not Found", {
          status: 404,
          headers: { "Cache-Control": "no-store" },
        });
    }
  }
  if (!isOrderSubmission(request)) return next();
  const response = (await guardOrderBody(request)) ?? (await next());
  response.headers.set("Cache-Control", "no-store");
  return response;
});
