import { defineMiddleware } from "astro:middleware";

import { adminOrigin, siteOrigins } from "./auth/public-origin";
import {
  decide,
  robots,
  sitemap,
  type PublicSite,
  type SiteEdition,
} from "./site-host-routing";

// Campaign hosts (specs/multi-domain §7.2). Runs first, before the closed
// guard: a request through the edge whose host is not a configured host is a
// campaign host candidate. Core decides whether it is active; the path is
// then mapped to the edition's campaign page, so the guard's rules (method
// allow-list, preview refusal, order POST admission) apply unchanged.

export interface SiteHostContext {
  readonly origin: URL;
  readonly site: PublicSite;
  readonly edition: SiteEdition | null;
}

const TTL_MS = 30_000;
const cache = new Map<string, { at: number; site: PublicSite | null }>();

export class SiteLookupError extends Error {}

/** Core's view of a host: null when it is not an active site host. */
export async function lookupSite(
  hostname: string,
  fetcher: typeof fetch = fetch,
): Promise<PublicSite | null> {
  const cached = cache.get(hostname);
  if (cached && Date.now() - cached.at < TTL_MS) return cached.site;
  const response = await fetcher(
    `http://api:8000/api/v1/public/sites/${encodeURIComponent(hostname)}`,
    { redirect: "error", signal: AbortSignal.timeout(2000) },
  );
  let site: PublicSite | null;
  if (response.status === 404) {
    await response.body?.cancel();
    site = null;
  } else if (
    response.ok &&
    response.headers.get("content-type")?.startsWith("application/json")
  ) {
    site = (await response.json()) as PublicSite;
    if (site.hostname !== hostname) throw new SiteLookupError();
  } else {
    await response.body?.cancel();
    throw new SiteLookupError();
  }
  if (cache.size > 500) cache.clear();
  cache.set(hostname, { at: Date.now(), site });
  return site;
}

/** The request's host when it came through the edge for a campaign host. */
export function campaignHostOf(request: Request): string | null {
  const host = request.headers.get("host")?.toLowerCase() ?? "";
  if (
    !host ||
    request.headers.get("x-forwarded-host")?.toLowerCase() !== host ||
    request.headers.get("x-forwarded-proto") !== "https" ||
    request.headers.has("forwarded")
  )
    return null;
  const configured = [adminOrigin(), ...siteOrigins()]
    .filter((origin): origin is URL => origin !== null)
    .map((origin) => origin.host);
  if (configured.includes(host)) return null;
  const hostname = host.replace(/:[0-9]+$/, "");
  return /^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}$/.test(
    hostname,
  )
    ? host
    : null;
}

const headers = { "Cache-Control": "no-store" };

// Plain error page of a campaign host, with the legal links (§7.7.2).
function notFoundPage(): Response {
  return new Response(
    '<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Seite nicht gefunden</title></head><body><main><h1>Seite nicht gefunden</h1><p>Unter dieser Adresse ist keine Aktionsseite veröffentlicht.</p><p><a href="/impressum">Impressum</a> · <a href="/datenschutz">Datenschutz</a></p></main></body></html>',
    {
      status: 404,
      headers: { ...headers, "Content-Type": "text/html; charset=utf-8" },
    },
  );
}

export const siteHostRouting = defineMiddleware(
  async ({ request, url, locals }, next) => {
    if (url.pathname.startsWith("/health/")) return next();
    const host = campaignHostOf(request);
    if (host === null) return next();
    const hostname = host.replace(/:[0-9]+$/, "");
    let site: PublicSite | null;
    try {
      site = await lookupSite(hostname);
    } catch {
      return new Response("Aktionsseite vorübergehend nicht erreichbar", {
        status: 503,
        headers: { ...headers, "Retry-After": "30" },
      });
    }
    const origin = new URL(`https://${host}`);
    const decision = decide(site, url, request.method);
    switch (decision.kind) {
      case "respond":
        if (decision.status === 404) return notFoundPage();
        return new Response(null, {
          status: decision.status,
          headers: {
            ...headers,
            ...(decision.location ? { Location: decision.location } : {}),
            ...(decision.status === 405 ? { Allow: "GET, HEAD" } : {}),
          },
        });
      case "robots":
        return new Response(robots(origin.origin), {
          headers: {
            "Content-Type": "text/plain; charset=utf-8",
            "Cache-Control": "public, max-age=300",
          },
        });
      case "sitemap":
        return new Response(sitemap(site!, origin.origin), {
          headers: {
            "Content-Type": "application/xml; charset=utf-8",
            "Cache-Control": "public, max-age=300",
          },
        });
      case "serve":
        locals.siteHost = { origin, site: site!, edition: decision.edition };
        return next(decision.path);
    }
  },
);
