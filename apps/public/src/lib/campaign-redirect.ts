import type { PublicActionRouteResponse } from "@leonaid/api-client";

/** Only Core-derived, published canonical campaign targets may redirect. */
export function campaignRedirect(
  route: PublicActionRouteResponse,
  method: string,
): Response | null {
  if (route.redirectPath == null) return null;
  const slug = route.action?.archiveSlug;
  if (
    route.routeKind !== "alias" ||
    route.availability !== "published" ||
    route.submissionsAllowed ||
    !slug ||
    /\s/.test(slug) ||
    !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug) ||
    route.redirectPath !== `/campaigns/${slug}/` ||
    route.canonicalPath !== route.redirectPath
  )
    return new Response(null, {
      status: 503,
      headers: { "Cache-Control": "no-store" },
    });
  if (method !== "GET" && method !== "HEAD")
    return new Response(null, {
      status: 405,
      headers: { Allow: "GET, HEAD", "Cache-Control": "no-store" },
    });
  return new Response(null, {
    status: 302,
    headers: {
      Location: route.redirectPath,
      "Cache-Control": "no-store",
      "X-LeonAid-Public-State": "redirect",
    },
  });
}
