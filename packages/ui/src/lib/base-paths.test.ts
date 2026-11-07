import { describe, expect, it } from "vitest";
import {
  DEFAULT_START_AREA_LABEL,
  adminHref,
  loginHref,
  pwaHref,
  redirectsToLogin,
  startAreaChoices,
} from "./base-paths";

describe("base paths (specs/multi-domain §6.7)", () => {
  it("builds paths below the two member apps", () => {
    expect(adminHref()).toBe("/admin/");
    expect(adminHref("/orders")).toBe("/admin/orders");
    expect(pwaHref("sponsors?view=new")).toBe("/app/sponsors?view=new");
  });

  it("keeps the deep link in the sign-in link", () => {
    expect(loginHref({ pathname: "/admin/orders", search: "?open=1" })).toBe(
      "/login?returnTo=%2Fadmin%2Forders%3Fopen%3D1",
    );
  });
});

describe("start-area choices (review B3)", () => {
  it("offers nothing to members with one app", () => {
    expect(startAreaChoices("web", { landingPath: "/app/" }, false)).toEqual(
      [],
    );
    expect(
      startAreaChoices(
        "pwa",
        { landingPath: "/admin/", preferredSurface: "web" },
        false,
      ),
    ).toEqual([]);
  });

  it("offers this app while the member lands in the other one", () => {
    expect(
      startAreaChoices(
        "web",
        { landingPath: "/app/", preferredSurface: null },
        true,
      ),
    ).toEqual([
      { surface: "web", label: "Verwaltung als Startbereich verwenden" },
    ]);
    expect(
      startAreaChoices("pwa", { landingPath: "/admin/system" }, true),
    ).toEqual([
      { surface: "pwa", label: "Akquise-App als Startbereich verwenden" },
    ]);
  });

  it("offers the default rule back after a choice, on both sides", () => {
    // Chose the admin app: the admin app offers the default, the PWA both.
    const choseWeb = {
      landingPath: "/admin/",
      preferredSurface: "web" as const,
    };
    expect(startAreaChoices("web", choseWeb, true)).toEqual([
      { surface: null, label: DEFAULT_START_AREA_LABEL },
    ]);
    expect(startAreaChoices("pwa", choseWeb, true)).toEqual([
      { surface: "pwa", label: "Akquise-App als Startbereich verwenden" },
      { surface: null, label: DEFAULT_START_AREA_LABEL },
    ]);
    const chosePwa = { landingPath: "/app/", preferredSurface: "pwa" as const };
    expect(startAreaChoices("pwa", chosePwa, true)).toEqual([
      { surface: null, label: DEFAULT_START_AREA_LABEL },
    ]);
  });
});

describe("sign-in redirect after a failed identity request", () => {
  it("redirects only without any session", () => {
    expect(
      redirectsToLogin({
        status: 401,
        detail: { code: "authentication_required" },
      }),
    ).toBe(true);
  });

  it("keeps the notice for an ended or revoked session and other errors", () => {
    for (const error of [
      { status: 401, detail: { code: "session_invalid" } },
      { status: 401, detail: {} },
      { status: 403, detail: { code: "authentication_required" } },
      { status: 500, detail: { code: "internal_error" } },
    ])
      expect(redirectsToLogin(error)).toBe(false);
  });
});
