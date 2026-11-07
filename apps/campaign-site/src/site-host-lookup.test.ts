import { afterEach, describe, expect, it, vi } from "vitest";

import { hasSecureSiteOrigin, siteOriginOf } from "./auth/public-origin";
import { campaignHostOf, lookupSite } from "./site-host-lookup";

// specs/multi-domain §7.2, §9.2: a campaign host is a candidate only through
// the edge, never a configured host, and counts as site origin only after
// Core returned it as active.
function request(host: string, headers: Record<string, string> = {}): Request {
  return new Request("http://campaign-site:3000/", {
    headers: {
      host,
      "x-forwarded-host": host,
      "x-forwarded-proto": "https",
      ...headers,
    },
  });
}

afterEach(() => {
  delete process.env.EMDASH_SITE_URL;
  delete process.env.LEONAID_SITE_BASE_URL;
});

describe("campaign host detection", () => {
  it("takes only unconfigured hosts that came through the edge", () => {
    process.env.EMDASH_SITE_URL = "https://app.leonaid.invalid/";
    process.env.LEONAID_SITE_BASE_URL = "https://leonaid.invalid/";
    expect(campaignHostOf(request("lionsopen.de"))).toBe("lionsopen.de");
    expect(campaignHostOf(request("krapfentaxi.test:8443"))).toBe(
      "krapfentaxi.test:8443",
    );
    expect(campaignHostOf(request("app.leonaid.invalid"))).toBeNull();
    expect(campaignHostOf(request("leonaid.invalid"))).toBeNull();
    expect(
      campaignHostOf(
        request("lionsopen.de", { "x-forwarded-host": "evil.test" }),
      ),
    ).toBeNull();
    expect(
      campaignHostOf(request("lionsopen.de", { "x-forwarded-proto": "http" })),
    ).toBeNull();
    expect(
      campaignHostOf(request("lionsopen.de", { forwarded: "x" })),
    ).toBeNull();
    expect(campaignHostOf(request("campaign-site:3000"))).toBeNull();
  });

  it("accepts a campaign host as site origin only when the middleware set it", () => {
    process.env.EMDASH_SITE_URL = "https://app.leonaid.invalid/";
    const page = request("lionsopen.de");
    expect(hasSecureSiteOrigin(page)).toBe(false);
    const validated = new URL("https://lionsopen.de");
    expect(hasSecureSiteOrigin(page, validated)).toBe(true);
    expect(siteOriginOf(page, validated)?.origin).toBe("https://lionsopen.de");
    // The middleware's host never validates a request for another host.
    expect(hasSecureSiteOrigin(request("evil.test"), validated)).toBe(false);
    const post = new Request("http://campaign-site:3000/", {
      method: "POST",
      headers: {
        host: "lionsopen.de",
        "x-forwarded-host": "lionsopen.de",
        "x-forwarded-proto": "https",
        origin: "https://evil.test",
      },
    });
    expect(hasSecureSiteOrigin(post, validated)).toBe(false);
  });
});

describe("Core lookup", () => {
  it("caches active and unknown hosts and fails closed on errors", async () => {
    const site = {
      hostname: "cached.example.org",
      kind: "campaign",
      redirectTo: null,
      root: null,
      editions: [],
      history: [],
    };
    const fetcher = vi.fn(
      async () =>
        new Response(JSON.stringify(site), {
          headers: { "Content-Type": "application/json" },
        }),
    );
    expect(await lookupSite("cached.example.org", fetcher)).toEqual(site);
    expect(await lookupSite("cached.example.org", fetcher)).toEqual(site);
    expect(fetcher).toHaveBeenCalledTimes(1);
    const missing = vi.fn(async () => new Response(null, { status: 404 }));
    expect(await lookupSite("missing.example.org", missing)).toBeNull();
    const broken = vi.fn(async () => new Response("x", { status: 500 }));
    await expect(lookupSite("broken.example.org", broken)).rejects.toThrow();
    const foreign = vi.fn(
      async () =>
        new Response(JSON.stringify({ ...site, hostname: "other.org" }), {
          headers: { "Content-Type": "application/json" },
        }),
    );
    await expect(lookupSite("foreign.example.org", foreign)).rejects.toThrow();
  });
});
