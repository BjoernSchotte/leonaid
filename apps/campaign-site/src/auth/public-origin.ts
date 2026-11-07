// Only the private Caddy ingress may supply these headers. Caddy overwrites
// forwarding headers; no CMS port is published. Identity never comes from them.
//
// Two kinds of origin (specs/multi-domain §6.4):
// - the admin origin EMDASH_SITE_URL: EmDash editor, setup, sign-in links;
// - the site origins: hosts that serve public campaign pages. Stage 1 has one,
//   LEONAID_SITE_BASE_URL (the public host); without it the single host is
//   both. Stage 2 adds the active campaign hosts, resolved through Core.

function configuredOrigin(value: string | undefined): URL | null {
  try {
    const origin = new URL(value ?? "");
    if (
      origin.protocol !== "https:" ||
      origin.username ||
      origin.password ||
      origin.pathname !== "/" ||
      origin.search ||
      origin.hash
    )
      return null;
    return origin;
  } catch {
    return null;
  }
}

/** The admin origin, or null when EMDASH_SITE_URL is not a plain HTTPS origin. */
export function adminOrigin(): URL | null {
  return configuredOrigin(process.env.EMDASH_SITE_URL);
}

/** Origins that serve public campaign pages. */
export function siteOrigins(): URL[] {
  const configured = process.env.LEONAID_SITE_BASE_URL?.trim();
  const origin = configured ? configuredOrigin(configured) : adminOrigin();
  return origin ? [origin] : [];
}

function forwardedFrom(request: Request, origin: URL): boolean {
  if (
    request.headers.get("host") !== origin.host ||
    request.headers.get("x-forwarded-host") !== origin.host ||
    request.headers.get("x-forwarded-proto") !== "https" ||
    request.headers.has("forwarded")
  )
    return false;
  const supplied = request.headers.get("origin");
  if (supplied !== null && supplied !== origin.origin) return false;
  if (!["GET", "HEAD"].includes(request.method) && supplied !== origin.origin)
    return false;
  return true;
}

/** Editor, setup and CMS API requests: only through the admin origin. */
export function hasSecureAdminOrigin(request: Request): boolean {
  const origin = adminOrigin();
  return origin !== null && forwardedFrom(request, origin);
}

/** The validated site origin a public campaign request came through. */
export function siteOriginOf(request: Request): URL | null {
  return siteOrigins().find((origin) => forwardedFrom(request, origin)) ?? null;
}

/** Public campaign pages and their order POSTs: only through a site origin. */
export function hasSecureSiteOrigin(request: Request): boolean {
  return siteOriginOf(request) !== null;
}

/**
 * The absolute public URL of a campaign page, for the editor's Live View.
 * Stage 2 returns the action's canonical URL on its campaign host instead.
 */
export function publicCampaignUrl(archiveSlug: string): string | null {
  const origin = siteOrigins()[0];
  if (!origin || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(archiveSlug)) return null;
  return new URL(`/campaigns/${archiveSlug}/`, origin).href;
}
