import { adminOrigin, siteOrigins } from "./auth/public-origin";
import {
  campaignHostname,
  configuredHostnames,
} from "../../public/src/lib/site-hosts";
import type { PublicSite } from "./site-host-routing";

// The Core lookup and host detection of the campaign host middleware
// (site-host.ts), kept free of Astro imports so they are unit-testable.

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

/** The request's host when it came through the edge for a campaign host.

The configured names are the same set the public app uses (one helper), plus
the CMS's own admin and site origins.
*/
export function campaignHostOf(
  request: Request,
  env: Record<string, string | undefined> = process.env,
): string | null {
  const host = request.headers.get("host")?.toLowerCase() ?? "";
  if (
    !host ||
    request.headers.get("x-forwarded-host")?.toLowerCase() !== host ||
    request.headers.get("x-forwarded-proto") !== "https" ||
    request.headers.has("forwarded")
  )
    return null;
  const configured = configuredHostnames(env);
  for (const origin of [adminOrigin(), ...siteOrigins()])
    if (origin) configured.add(origin.hostname);
  return campaignHostname(host, configured) === null ? null : host;
}
