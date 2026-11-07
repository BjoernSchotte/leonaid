import { describe, expect, it, vi } from "vitest";
import type { PublicCampaignListItemResponse } from "@leonaid/api-client";
import {
  adminOnlyTarget,
  admitHost,
  campaignHostname,
  campaignHref,
  canonicalRedirect,
  configuredHostnames,
  createSiteHostCheck,
  hasPublicHost,
  publicRobots,
  publicSitemap,
} from "./site-hosts";

// specs/multi-domain §6.5, §6.6, §7.5, §7.7.3, §9.2.
const configured = configuredHostnames({
  LEONAID_ADMIN_DOMAIN: "app.example.org",
  LEONAID_PUBLIC_DOMAIN: "example.org",
  LEONAID_PUBLIC_DOMAIN_ALIASES: "www.example.org",
});

function campaign(
  canonicalPath: string,
  canonicalUrl: string,
): PublicCampaignListItemResponse {
  return {
    archiveSlug: "x",
    canonicalPath,
    canonicalUrl,
    carrierName: "Lions",
    endsOn: "2026-12-31",
    name: "X",
    presentationTheme: null,
    purpose: "Zweck",
    startsOn: "2026-01-01",
  };
}

describe("campaign hosts in the public app", () => {
  it("looks up only names that are not this installation's hosts", () => {
    expect(campaignHostname("lionsopen.de", configured)).toBe("lionsopen.de");
    expect(campaignHostname("Krapfentaxi.ORG:443", configured)).toBe(
      "krapfentaxi.org",
    );
    for (const host of [
      "example.org",
      "app.example.org:443",
      "www.example.org",
      "localhost:8443",
      "app.localhost:8443",
      "proxy:8443",
      "public:3000",
      "192.168.1.20:28081",
      "",
    ])
      expect(campaignHostname(host, configured)).toBeNull();
  });

  it("refuses a lapsed or removed host although its certificate still works", async () => {
    // Acceptance (review of #105): Caddy keeps serving a certificate it
    // already holds; the app itself must refuse every non-active host.
    const inactive = async () => null;
    expect(await admitHost("lionsopen.de", configured, inactive)).toEqual({
      admit: "refuse",
    });
    expect(
      await admitHost("lionsopen.de", configured, async () => {
        throw new Error("core down");
      }),
    ).toEqual({ admit: "unavailable" });
    expect(
      await admitHost("lionsopen.de", configured, async () => ({
        kind: "campaign" as const,
      })),
    ).toEqual({ admit: "serve" });
    expect(await admitHost("example.org", configured, inactive)).toEqual({
      admit: "serve",
    });
  });

  it("redirects a redirect host as a whole (review M2)", async () => {
    expect(
      await admitHost("www.lionsopen.de", configured, async () => ({
        kind: "redirect" as const,
        to: "https://lionsopen.de",
      })),
    ).toEqual({ admit: "redirect", to: "https://lionsopen.de" });
    expect(
      await admitHost("www.lionsopen.de", configured, async () => ({
        kind: "redirect" as const,
        to: "javascript:alert(1)",
      })),
    ).toEqual({ admit: "unavailable" });
  });

  it("caches Core's answer for 30 s", async () => {
    let now = 0;
    const lookup = vi.fn(
      async (hostname: string) => hostname === "a.example.net",
    );
    const check = createSiteHostCheck(lookup, () => now);
    expect(await check("a.example.net")).toBe(true);
    expect(await check("b.example.net")).toBe(false);
    expect(await check("a.example.net")).toBe(true);
    expect(lookup).toHaveBeenCalledTimes(2);
    now = 31_000;
    await check("a.example.net");
    expect(lookup).toHaveBeenCalledTimes(3);
  });

  it("redirects with 302 to a host root and 308 to a segment", () => {
    expect(canonicalRedirect("https://lionsopen.de/").status).toBe(302);
    // Only the shapes Core builds (review M4).
    for (const odd of [
      "//evil.example/",
      "http://lionsopen.de/",
      "https://lionsopen.de/a/b/",
      "https://user@evil.example/",
      "javascript:alert(1)",
    ])
      expect(canonicalRedirect(odd).status).toBe(503);
    const segment = canonicalRedirect("https://lionsopen.de/2025/");
    expect(segment.status).toBe(308);
    expect(segment.headers.get("Location")).toBe("https://lionsopen.de/2025/");
  });

  it("links home cards relative on this host, absolute on a campaign host", () => {
    expect(
      campaignHref(
        campaign("/campaigns/x/", "https://example.org/campaigns/x/"),
      ),
    ).toBe("/campaigns/x/");
    expect(
      campaignHref(campaign("/campaigns/x/", "https://lionsopen.de/")),
    ).toBe("https://lionsopen.de/");
  });

  it("lists home and this host's pages in the sitemap, never redirects", () => {
    const xml = publicSitemap(
      "https://example.org",
      [
        campaign("/campaigns/x/", "https://example.org/campaigns/x/"),
        campaign("/campaigns/y/", "https://lionsopen.de/"),
      ],
      true,
    );
    expect(xml).toContain("<loc>https://example.org/</loc>");
    expect(xml).toContain("<loc>https://example.org/campaigns/x/</loc>");
    expect(xml).not.toContain("/campaigns/y/");
    expect(xml).not.toContain("lionsopen.de");
    expect(publicRobots("https://example.org", true)).toContain(
      "Sitemap: https://example.org/sitemap.xml",
    );
  });

  it("maps admin-host paths without a public host to Core routes only", () => {
    // N4: aliases, archive and campaign paths only redirect or 404.
    expect(adminOnlyTarget(["krapfentaxi"])).toEqual({
      routeKind: "alias",
      routeValue: "krapfentaxi",
    });
    expect(adminOnlyTarget(["archive", "lions-open-2025"])).toEqual({
      routeKind: "archive",
      routeValue: "lions-open-2025",
    });
    expect(adminOnlyTarget(["campaigns", "lions-open-2025"])).toEqual({
      routeKind: "archive",
      routeValue: "lions-open-2025",
    });
    for (const segments of [
      [],
      ["campaigns", "x", "media", "y"],
      ["Bad Alias"],
      ["a", "b"],
    ])
      expect(adminOnlyTarget(segments)).toBeNull();
  });

  it("lists nothing on an admin host without a public host", () => {
    expect(
      hasPublicHost({
        LEONAID_ADMIN_DOMAIN: "app.example.org",
        LEONAID_PUBLIC_DOMAIN: "",
      }),
    ).toBe(false);
    expect(hasPublicHost({ LEONAID_PUBLIC_DOMAIN: "portal.example.org" })).toBe(
      true,
    );
    expect(hasPublicHost({})).toBe(true);
    expect(publicSitemap("https://app.example.org", [], false)).not.toContain(
      "<loc>",
    );
    expect(publicRobots("https://app.example.org", false)).toContain(
      "Disallow: /",
    );
  });
});
