import { describe, expect, it } from "vitest";
import {
  decide,
  EDITIONS_PAGE,
  redirectStatus,
  robots,
  sitemap,
  type PublicSite,
  type SiteEdition,
} from "./site-host-routing";

// specs/multi-domain §7.7.2: the routing table of a campaign host.
const HOST = "https://lionsopen.de";
const MEDIA = "01JC0000000000000000000000";

function edition(fields: Partial<SiteEdition>): SiteEdition {
  return {
    segment: "2025",
    atRoot: false,
    isPrimary: true,
    archiveSlug: "lions-open-2025",
    availability: "archive",
    title: "Lions Open 2025",
    startsOn: "2025-05-01",
    endsOn: "2025-06-30",
    editionUrl: `${HOST}/2025/`,
    canonicalUrl: `${HOST}/2025/`,
    ...fields,
  };
}

const running = edition({
  segment: "2026",
  atRoot: true,
  archiveSlug: "lions-open-2026",
  availability: "published",
  title: "Lions Open 2026",
  editionUrl: `${HOST}/2026/`,
  canonicalUrl: `${HOST}/`,
});
const ended = edition({});

function site(fields: Partial<PublicSite> = {}): PublicSite {
  return {
    hostname: "lionsopen.de",
    kind: "campaign",
    redirectTo: null,
    root: { segment: "2026", mode: "serve" },
    editions: [running, ended],
    history: [
      {
        segment: "lo-2024",
        archiveSlug: "lions-open-2024",
        targetUrl: "https://club.example.org/archive/lions-open-2024",
        status: 308,
      },
    ],
    ...fields,
  };
}

function go(path: string, method = "GET", target = site()) {
  return decide(target, new URL(path, HOST), method);
}

describe("campaign host routing", () => {
  it("serves the running root edition at /", () => {
    expect(go("/")).toEqual({
      kind: "serve",
      path: "/campaigns/lions-open-2026/",
      edition: running,
    });
    expect(go("/?_action=createPublicOrder", "POST")).toMatchObject({
      kind: "serve",
      path: "/campaigns/lions-open-2026/?_action=createPublicOrder",
    });
  });

  it("302s / to the fallback edition when the root does not run", () => {
    const after = site({ root: { segment: "2025", mode: "redirect" } });
    expect(go("/?ref=qr", "GET", after)).toEqual({
      kind: "respond",
      status: 302,
      location: "/2025/?ref=qr",
    });
    expect(go("/", "GET", site({ root: null, editions: [] }))).toEqual({
      kind: "respond",
      status: 404,
    });
  });

  it("302s the segment of the running root edition to /", () => {
    expect(go("/2026/?x=1")).toEqual({
      kind: "respond",
      status: 302,
      location: "/?x=1",
    });
  });

  it("serves any other live segment, ended ones as archive", () => {
    expect(go("/2025/")).toEqual({
      kind: "serve",
      path: "/campaigns/lions-open-2025/",
      edition: ended,
    });
    expect(go("/2025")).toEqual({
      kind: "respond",
      status: 308,
      location: "/2025/",
    });
    expect(go("/2025/anything")).toEqual({ kind: "respond", status: 404 });
  });

  it("308s history segments to the action's canonical URL", () => {
    expect(go("/lo-2024/")).toEqual({
      kind: "respond",
      status: 308,
      location: "https://club.example.org/archive/lions-open-2024",
    });
  });

  it("lists the editions at /archive/ and redirects archive and campaign paths", () => {
    expect(go("/archive/")).toEqual({
      kind: "serve",
      path: EDITIONS_PAGE,
      edition: null,
    });
    expect(go("/archive")).toEqual({
      kind: "respond",
      status: 308,
      location: "/archive/",
    });
    expect(go("/archive/lions-open-2025")).toEqual({
      kind: "respond",
      status: 308,
      location: `${HOST}/2025/`,
    });
    expect(go("/campaigns/lions-open-2026/")).toEqual({
      kind: "respond",
      status: 302,
      location: `${HOST}/`,
    });
    expect(go("/campaigns/other-campaign/")).toEqual({
      kind: "respond",
      status: 404,
    });
    expect(go("/archive/other-campaign")).toEqual({
      kind: "respond",
      status: 404,
    });
  });

  it("serves media of every edition of this host, never of others", () => {
    expect(go(`/campaigns/lions-open-2025/media/${MEDIA}`)).toMatchObject({
      kind: "serve",
      path: `/campaigns/lions-open-2025/media/${MEDIA}`,
    });
    expect(go(`/campaigns/lions-open-2024/media/${MEDIA}`)).toMatchObject({
      kind: "serve",
    });
    expect(go(`/campaigns/krapfentaxi-2026/media/${MEDIA}`)).toEqual({
      kind: "respond",
      status: 404,
    });
  });

  it("answers 404 for unknown hosts, other paths and editor paths", () => {
    expect(decide(null, new URL("/", HOST), "GET")).toEqual({
      kind: "respond",
      status: 404,
    });
    for (const path of [
      "/_emdash/admin/",
      "/krapfentaxi",
      "/x/y",
      "/site-editions",
    ])
      expect(go(path)).toEqual({ kind: "respond", status: 404 });
  });

  it("refuses writes everywhere but an edition page", () => {
    expect(go("/archive/", "POST")).toEqual({ kind: "respond", status: 405 });
    expect(go("/2025/?_action=createPublicOrder", "POST")).toMatchObject({
      kind: "serve",
      path: "/campaigns/lions-open-2025/?_action=createPublicOrder",
    });
    expect(go("/2026/", "POST")).toEqual({ kind: "respond", status: 405 });
  });

  it("redirects a redirect host as a whole, path and query kept", () => {
    const www = site({ kind: "redirect", redirectTo: HOST, root: null });
    expect(go("/2025/?x=1", "GET", www)).toEqual({
      kind: "respond",
      status: 308,
      location: `${HOST}/2025/?x=1`,
    });
  });

  it("uses 302 for host roots and 308 otherwise", () => {
    expect(redirectStatus(`${HOST}/`)).toBe(302);
    expect(redirectStatus(`${HOST}/2025/`)).toBe(308);
  });

  it("lists only canonical URLs of this host in the sitemap", () => {
    const mirror = edition({
      segment: "2023",
      archiveSlug: "lions-open-2023",
      canonicalUrl: "https://lionsopen.example.org/",
    });
    const xml = sitemap(site({ editions: [running, ended, mirror] }), HOST);
    expect(xml).toContain(`<loc>${HOST}/</loc>`);
    expect(xml).toContain(`<loc>${HOST}/2025/</loc>`);
    expect(xml).toContain(`<loc>${HOST}/archive/</loc>`);
    expect(xml).not.toContain("lionsopen.example.org");
    expect(xml).not.toContain("/campaigns/");
    expect(robots(HOST)).toContain(`Sitemap: ${HOST}/sitemap.xml`);
  });
});
