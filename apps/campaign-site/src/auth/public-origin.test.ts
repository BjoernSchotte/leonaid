import { afterEach, describe, expect, it } from "vitest";
import {
  hasSecureAdminOrigin,
  hasSecureSiteOrigin,
  publicCampaignUrl,
  siteOriginOf,
} from "./public-origin";

const ADMIN = "https://app.leonaid.invalid";
const PUBLIC = "https://leonaid.invalid";

function request(
  host: string,
  {
    method = "GET",
    origin,
    proto = "https",
    forwardedHost = host,
  }: {
    method?: string;
    origin?: string;
    proto?: string;
    forwardedHost?: string;
  } = {},
): Request {
  const headers = new Headers({
    host,
    "x-forwarded-host": forwardedHost,
    "x-forwarded-proto": proto,
  });
  if (origin) headers.set("origin", origin);
  return new Request(`http://campaign-site:3000/campaigns/a/`, {
    method,
    headers,
  });
}

function configure(site?: string): void {
  process.env.EMDASH_SITE_URL = `${ADMIN}/`;
  if (site === undefined) delete process.env.LEONAID_SITE_BASE_URL;
  else process.env.LEONAID_SITE_BASE_URL = site;
}

afterEach(() => {
  delete process.env.EMDASH_SITE_URL;
  delete process.env.LEONAID_SITE_BASE_URL;
});

describe("admin and site origins (specs/multi-domain §6.4)", () => {
  it("binds the editor to the admin host and campaign pages to the public host", () => {
    configure(PUBLIC);
    const admin = request("app.leonaid.invalid");
    const site = request("leonaid.invalid");

    expect(hasSecureAdminOrigin(admin)).toBe(true);
    expect(hasSecureSiteOrigin(admin)).toBe(false);
    expect(hasSecureSiteOrigin(site)).toBe(true);
    expect(hasSecureAdminOrigin(site)).toBe(false);
    expect(siteOriginOf(site)?.origin).toBe(PUBLIC);
    expect(publicCampaignUrl("krapfentaxi-2026")).toBe(
      `${PUBLIC}/campaigns/krapfentaxi-2026/`,
    );
  });

  it("uses the one host for both without a public host", () => {
    configure();
    const single = request("app.leonaid.invalid");

    expect(hasSecureAdminOrigin(single)).toBe(true);
    expect(hasSecureSiteOrigin(single)).toBe(true);
    expect(publicCampaignUrl("a")).toBe(`${ADMIN}/campaigns/a/`);
    configure("");
    expect(siteOriginOf(single)?.origin).toBe(ADMIN);
  });

  it("requires the site's own Origin for an order POST", () => {
    configure(PUBLIC);
    const host = "leonaid.invalid";

    expect(
      hasSecureSiteOrigin(request(host, { method: "POST", origin: PUBLIC })),
    ).toBe(true);
    for (const origin of [undefined, ADMIN, "https://evil.invalid"])
      expect(
        hasSecureSiteOrigin(request(host, { method: "POST", origin })),
      ).toBe(false);
  });

  it("rejects forged forwarding and plain HTTP", () => {
    configure(PUBLIC);

    expect(
      hasSecureSiteOrigin(
        request("leonaid.invalid", { forwardedHost: "evil.invalid" }),
      ),
    ).toBe(false);
    expect(
      hasSecureSiteOrigin(request("leonaid.invalid", { proto: "http" })),
    ).toBe(false);
    expect(hasSecureSiteOrigin(request("evil.invalid"))).toBe(false);
  });

  it("rejects site base URLs that are not plain HTTPS origins", () => {
    for (const site of [
      "http://leonaid.invalid",
      "https://leonaid.invalid/campaigns/",
      "https://user:secret@leonaid.invalid",
      "not a url",
    ]) {
      configure(site);
      expect(hasSecureSiteOrigin(request("leonaid.invalid"))).toBe(false);
      expect(publicCampaignUrl("a")).toBeNull();
    }
    configure(PUBLIC);
    expect(publicCampaignUrl("../admin")).toBeNull();
  });
});
