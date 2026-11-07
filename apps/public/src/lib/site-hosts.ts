// Campaign hosts in the public app (specs/multi-domain §6.6, §7). On a
// campaign host the edge routes only legal pages, static files and the order
// RPC here; this module decides whether the host is one Core serves, where
// a public page of an action with a campaign host redirects, and what the
// public host's sitemap lists.

import type { PublicCampaignListItemResponse } from "@leonaid/api-client";
import { runtimeHostnames } from "../../runtime-allowed-domains.mjs";

/** Names of this installation from the environment, plus in-network names. */
export function configuredHostnames(
  env: Record<string, string | undefined> = process.env,
): Set<string> {
  return new Set([
    "localhost",
    "127.0.0.1",
    "proxy",
    "public",
    ...runtimeHostnames([
      env.LEONAID_ADMIN_DOMAIN,
      env.LEONAID_PUBLIC_DOMAIN,
      env.LEONAID_PUBLIC_DOMAIN_ALIASES,
      env.LEONAID_LAN_HOST,
      env.LEONAID_REMOTE_HOST,
    ]),
  ]);
}

const DOMAIN = /^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}$/;

/** The hostname to look up in Core, or null for a configured host or an IP. */
export function campaignHostname(
  hostHeader: string | null,
  configured: Set<string>,
): string | null {
  const hostname = (hostHeader ?? "").toLowerCase().replace(/:[0-9]+$/, "");
  if (!hostname || configured.has(hostname) || hostname.endsWith(".localhost"))
    return null;
  return DOMAIN.test(hostname) ? hostname : null;
}

/**
 * Whether the public app serves this request (§9.2): configured hosts
 * always; any other name only while Core returns it as an active campaign
 * host. A lapsed or removed host is refused here even while Caddy still
 * holds its certificate.
 */
export async function admitHost(
  hostHeader: string | null,
  configured: Set<string>,
  isActive: (hostname: string) => Promise<boolean>,
): Promise<"serve" | "refuse" | "unavailable"> {
  const hostname = campaignHostname(hostHeader, configured);
  if (hostname === null) return "serve";
  try {
    return (await isActive(hostname)) ? "serve" : "refuse";
  } catch {
    return "unavailable";
  }
}

const TTL_MS = 30_000;
type Lookup = (hostname: string) => Promise<boolean>;

/** Active campaign hosts, cached 30 s, positive and negative. */
export function createSiteHostCheck(lookup: Lookup, clock = Date.now) {
  const cache = new Map<string, { at: number; active: boolean }>();
  return async (hostname: string): Promise<boolean> => {
    const cached = cache.get(hostname);
    if (cached && clock() - cached.at < TTL_MS) return cached.active;
    const active = await lookup(hostname);
    if (cache.size > 500) cache.clear();
    cache.set(hostname, { at: clock(), active });
    return active;
  };
}

/** 302 to a host root (reused by the next edition), else 308 (§7.7.3). */
export function canonicalRedirect(target: string): Response {
  return new Response(null, {
    status: new URL(target).pathname === "/" ? 302 : 308,
    headers: {
      Location: target,
      "Cache-Control": "no-store",
      "X-LeonAid-Public-State": "redirect",
    },
  });
}

/** The link of a home-page card: relative on this host, else absolute. */
export function campaignHref(campaign: PublicCampaignListItemResponse): string {
  return new URL(campaign.canonicalUrl).pathname === campaign.canonicalPath
    ? campaign.canonicalPath
    : campaign.canonicalUrl;
}

function escapeXml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * The public host's sitemap (§6.5, §7.5): the home page and the canonical
 * URLs that live on this host. Without a public host (§6.6) the admin host
 * lists nothing.
 */
export function publicSitemap(
  origin: string,
  campaigns: readonly PublicCampaignListItemResponse[],
  hasPublicHost: boolean,
): string {
  const urls = hasPublicHost
    ? [
        `${origin}/`,
        ...campaigns
          .filter(
            (campaign) => campaignHref(campaign) === campaign.canonicalPath,
          )
          .map((campaign) => `${origin}${campaign.canonicalPath}`),
      ]
    : [];
  const entries = [...new Set(urls)]
    .map((url) => `  <url><loc>${escapeXml(url)}</loc></url>`)
    .join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${entries}\n</urlset>\n`;
}

export function publicRobots(origin: string, hasPublicHost: boolean): string {
  return hasPublicHost
    ? `User-agent: *\nAllow: /\nSitemap: ${origin}/sitemap.xml\n`
    : "User-agent: *\nDisallow: /\n";
}

/** False only for an admin host without a general public host (§6.6). */
export function hasPublicHost(
  env: Record<string, string | undefined> = process.env,
): boolean {
  return (
    Boolean(env.LEONAID_PUBLIC_DOMAIN?.trim()) ||
    !env.LEONAID_ADMIN_DOMAIN?.trim()
  );
}
