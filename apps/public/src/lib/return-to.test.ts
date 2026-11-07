import { describe, expect, it } from "vitest";
import { entryDestination } from "./entry";
import { memberReturnTo } from "./return-to";

describe("deep links through the login (specs/multi-domain §6.7)", () => {
  it("keeps paths below the member apps and the CMS editor", () => {
    for (const path of [
      "/admin/orders?commitment=1",
      "/admin/",
      "/admin",
      "/app/activities?view=contacts&assignment=x",
      "/app/",
      "/_emdash/admin/content/campaign_pages",
    ])
      expect(memberReturnTo(path, "/app/")).toBe(path);
  });

  it("falls back for public pages, other hosts and escapes", () => {
    for (const path of [
      "/campaigns/krapfentaxi-2026/",
      "/krapfentaxi",
      "/administration",
      "/apple",
      "https://evil.invalid/admin/",
      "//evil.invalid/admin/",
      "/%2fevil.invalid/admin/",
      "/admin\\..\\evil",
    ])
      expect(memberReturnTo(path, "/app/")).toBe("/app/");
  });

  it("redirects the entry only to Core's landing path", () => {
    expect(entryDestination("/admin/system", "/admin/")).toBe("/admin/system");
    expect(entryDestination("/app/", "/admin/")).toBe("/app/");
    expect(entryDestination("https://evil.invalid/", "/admin/")).toBe(
      "/admin/",
    );
    expect(entryDestination(undefined, "/admin/")).toBe("/admin/");
    expect(entryDestination(42, "/admin/")).toBe("/admin/");
  });
});
