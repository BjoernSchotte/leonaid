// Campaign hosts (specs/multi-domain §7.2, §7.7.2). Every request whose host
// is not one of the configured hosts is looked up in Core; only an active
// campaign host is served. The decision is a pure function of Core's answer
// and the URL, so the routing table is testable without a server.

export type EditionAvailability = "published" | "archive" | "inactive";

export interface SiteEdition {
  readonly segment: string;
  readonly atRoot: boolean;
  readonly isPrimary: boolean;
  readonly archiveSlug: string;
  readonly availability: EditionAvailability;
  readonly title: string;
  readonly startsOn: string;
  readonly endsOn: string;
  readonly editionUrl: string;
  readonly canonicalUrl: string | null;
}

export interface SiteHistory {
  readonly segment: string;
  readonly archiveSlug: string;
  readonly targetUrl: string;
  readonly status: number;
}

export interface PublicSite {
  readonly hostname: string;
  readonly kind: "campaign" | "redirect";
  readonly redirectTo: string | null;
  readonly root: {
    readonly segment: string;
    readonly mode: "serve" | "redirect";
  } | null;
  readonly editions: readonly SiteEdition[];
  readonly history: readonly SiteHistory[];
}

export type SiteDecision =
  | {
      readonly kind: "respond";
      readonly status: number;
      readonly location?: string;
    }
  | {
      readonly kind: "serve";
      // The internal path the campaign site renders.
      readonly path: string;
      readonly edition: SiteEdition | null;
    }
  | { readonly kind: "robots" }
  | { readonly kind: "sitemap" };

const SLUG = "[a-z0-9]+(?:-[a-z0-9]+)*";
const MEDIA_ID = "[0-9A-HJKMNP-TV-Z]{26}";
// The internal page with the edition list (never routed by Caddy itself).
export const EDITIONS_PAGE = "/site-editions";

const notFound: SiteDecision = { kind: "respond", status: 404 };

/** 302 to a host root (reused by the next edition), else 308 (§7.7.3). */
export function redirectStatus(target: string): 302 | 308 {
  const url = new URL(target, "https://placeholder.invalid");
  return url.pathname === "/" ? 302 : 308;
}

function redirect(
  target: string,
  search: string,
  status?: number,
): SiteDecision {
  const location = target + (target.includes("?") ? "" : search);
  return {
    kind: "respond",
    status: status ?? redirectStatus(target),
    location,
  };
}

function servePage(edition: SiteEdition, search: string): SiteDecision {
  return {
    kind: "serve",
    path: `/campaigns/${edition.archiveSlug}/${search}`,
    edition,
  };
}

export function decide(
  site: PublicSite | null,
  url: URL,
  method: string,
): SiteDecision {
  if (!site) return notFound;
  const read = method === "GET" || method === "HEAD";
  const path = url.pathname;
  const search = url.search;
  if (site.kind === "redirect") {
    if (!site.redirectTo) return notFound;
    // Whole host, path and query kept (§7.1).
    return redirect(site.redirectTo + path, search, 308);
  }
  const bySegment = new Map(site.editions.map((item) => [item.segment, item]));
  const bySlug = new Map(site.editions.map((item) => [item.archiveSlug, item]));
  const historySegment = new Map(
    site.history.map((item) => [item.segment, item]),
  );
  const historySlug = new Map(
    site.history.map((item) => [item.archiveSlug, item]),
  );
  const canonicalOf = (slug: string): SiteDecision => {
    const edition = bySlug.get(slug);
    if (edition?.canonicalUrl) return redirect(edition.canonicalUrl, search);
    const moved = historySlug.get(slug);
    if (moved) return redirect(moved.targetUrl, search, moved.status);
    return notFound;
  };

  // The native order POST is the only write; it posts to the page's own URL.
  if (path === "/") {
    if (!site.root) return notFound;
    const edition = bySegment.get(site.root.segment);
    if (!edition) return notFound;
    if (site.root.mode === "serve") return servePage(edition, search);
    if (!read) return { kind: "respond", status: 405 };
    // Temporary: "/" is reused by the next edition.
    return {
      kind: "respond",
      status: 302,
      location: `/${edition.segment}/${search}`,
    };
  }
  if (!read) {
    const segment = new RegExp(`^/(${SLUG})/$`).exec(path);
    const edition = segment ? bySegment.get(segment[1]!) : undefined;
    if (edition && !(edition.atRoot && edition.availability === "published"))
      return servePage(edition, search);
    return { kind: "respond", status: 405 };
  }
  if (path === "/robots.txt") return { kind: "robots" };
  if (path === "/sitemap.xml") return { kind: "sitemap" };
  if (path === "/archive")
    return { kind: "respond", status: 308, location: `/archive/${search}` };
  if (path === "/archive/") {
    if (!site.editions.length) return notFound;
    return { kind: "serve", path: EDITIONS_PAGE, edition: null };
  }
  let match = new RegExp(`^/archive/(${SLUG})/?$`).exec(path);
  if (match) return canonicalOf(match[1]!);
  match = new RegExp(`^/campaigns/(${SLUG})/media/(${MEDIA_ID})$`).exec(path);
  if (match) {
    // Media of every edition bound to this host, live or history (§7.5).
    const slug = match[1]!;
    if (!bySlug.has(slug) && !historySlug.has(slug)) return notFound;
    return { kind: "serve", path, edition: bySlug.get(slug) ?? null };
  }
  match = new RegExp(`^/campaigns/(${SLUG})/?$`).exec(path);
  if (match) return canonicalOf(match[1]!);
  match = new RegExp(`^/(${SLUG})(/.*)?$`).exec(path);
  if (match) {
    const [, segment, rest] = match;
    const edition = bySegment.get(segment!);
    if (edition) {
      if (rest === undefined)
        return {
          kind: "respond",
          status: 308,
          location: `/${segment}/${search}`,
        };
      if (rest !== "/") return notFound;
      if (edition.atRoot && edition.availability === "published")
        // Temporary on purpose: a cached 308 would later send /2025/ to 2026.
        // Only "/" itself: never a Location built from the request path.
        return { kind: "respond", status: 302, location: `/${search}` };
      return servePage(edition, search);
      return notFound;
    }
    const moved = historySegment.get(segment!);
    if (moved) return redirect(moved.targetUrl, search, moved.status);
  }
  return notFound;
}

function escapeXml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * Canonical URLs that live on this host: the running root edition at "/",
 * every other edition at its segment, plus the edition list. Redirecting
 * URLs (history, aliases, /campaigns/<slug>/) are never listed (§7.5).
 */
export function sitemap(site: PublicSite, origin: string): string {
  const urls = new Set<string>();
  for (const edition of site.editions) {
    const canonical = edition.canonicalUrl;
    if (canonical && new URL(canonical).origin === origin) urls.add(canonical);
  }
  if (site.editions.length) urls.add(`${origin}/archive/`);
  const entries = [...urls]
    .sort()
    .map((url) => `  <url><loc>${escapeXml(url)}</loc></url>`)
    .join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${entries}\n</urlset>\n`;
}

export function robots(origin: string): string {
  return `User-agent: *\nAllow: /\nSitemap: ${origin}/sitemap.xml\n`;
}
