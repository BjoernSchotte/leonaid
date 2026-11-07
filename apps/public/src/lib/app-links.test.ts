// @vitest-environment jsdom
import { ApiError, type NavigationItemResponse } from "@leonaid/api-client";
import { describe, expect, it } from "vitest";

import {
  adminHostLink,
  appLinksFor,
  loadAppLinks,
  renderAppLinks,
} from "./app-links";

const item = (
  key: string,
  href: string,
  surface: "web" | "pwa",
): NavigationItemResponse => ({ key, href, label: key, surface });

// Every signed-in account gets the PWA overview and the module items.
const everyone = [
  item("overview-pwa", "/app/", "pwa"),
  item("tasks", "/admin/tasks", "web"),
  item("tasks", "/app/tasks", "pwa"),
  item("surveys", "/admin/surveys", "web"),
  item("surveys", "/admin/surveys", "pwa"),
];
const adminOnly = [
  item("overview-web", "/admin/", "web"),
  ...everyone,
  item("invoices", "/admin/invoices", "web"),
];
const acquirerOnly = [
  ...everyone,
  item("sponsors", "/app/sponsors", "pwa"),
  item("commitment", "/app/commitments/new", "pwa"),
  item("activities", "/app/activities", "pwa"),
];
const both = [
  item("overview-web", "/admin/", "web"),
  ...everyone,
  item("activities", "/admin/activities", "web"),
  item("acquisition-pwa", "/app/acquisition", "pwa"),
];

const identity = (navigation: NavigationItemResponse[]) => ({
  getCurrentIdentity: async () => ({ navigation }),
});

function container(): HTMLElement {
  const nav = document.createElement("nav");
  nav.hidden = true;
  return nav;
}

function rendered(nav: HTMLElement) {
  return [...nav.querySelectorAll("a")].map((link) => [
    link.textContent,
    link.getAttribute("href"),
  ]);
}

describe("public header app links", () => {
  it("stay hidden for signed-out visitors", async () => {
    const nav = container();
    const links = await loadAppLinks({
      getCurrentIdentity: async () => {
        throw new ApiError(401, {
          code: "authentication_required",
          message: "Bitte anmelden, um LeonAid zu verwenden.",
          requestId: "",
        });
      },
    });
    renderAppLinks(nav, links);
    expect(links).toEqual([]);
    expect(nav.hidden).toBe(true);
    expect(nav.children).toHaveLength(0);
  });

  it("stay hidden when the identity request fails", async () => {
    const nav = container();
    renderAppLinks(
      nav,
      await loadAppLinks({
        getCurrentIdentity: async () => {
          throw new TypeError("Failed to fetch");
        },
      }),
    );
    expect(nav.hidden).toBe(true);
    // A malformed answer counts as no answer.
    expect(
      await loadAppLinks({
        getCurrentIdentity: async () =>
          ({}) as { navigation: NavigationItemResponse[] },
      }),
    ).toEqual([]);
  });

  it("show only the admin app for back-office roles", async () => {
    const nav = container();
    renderAppLinks(nav, await loadAppLinks(identity(adminOnly)));
    expect(nav.hidden).toBe(false);
    expect(rendered(nav)).toEqual([["Zur Verwaltung", "/admin/"]]);
  });

  it("show only the PWA for acquirers", async () => {
    const nav = container();
    renderAppLinks(nav, await loadAppLinks(identity(acquirerOnly)));
    expect(rendered(nav)).toEqual([["Zur Akquise-App", "/app/"]]);
  });

  it("show both apps when the account works in both", async () => {
    const nav = container();
    renderAppLinks(nav, await loadAppLinks(identity(both)));
    expect(rendered(nav)).toEqual([
      ["Zur Verwaltung", "/admin/"],
      ["Zur Akquise-App", "/app/"],
    ]);
  });

  it("ignore module items and the PWA overview every account gets", () => {
    expect(appLinksFor(everyone)).toEqual([]);
    expect(appLinksFor([])).toEqual([]);
  });

  it("keep header links on this origin", () => {
    expect(
      appLinksFor([
        item("overview-web", "https://example.invalid/admin/", "web"),
        item("overview-pwa", "//example.invalid/app/", "pwa"),
        item("delivery", "/app/delivery", "pwa"),
      ]).map((link) => link.href),
    ).toEqual(["/admin/", "/app/"]);
  });
});

describe("admin host link (specs/multi-domain)", () => {
  it("links the public host statically to the admin host", () => {
    expect(adminHostLink("https://app.club.org", "club.org")).toEqual({
      href: "https://app.club.org/",
      label: "Anmelden",
    });
    expect(
      adminHostLink("https://app.localhost:28443/", "localhost:28443"),
    ).toEqual({ href: "https://app.localhost:28443/", label: "Anmelden" });
  });

  it("keeps the identity-based links on the admin host and with one host", () => {
    expect(adminHostLink("https://app.club.org", "app.club.org")).toBeNull();
    expect(adminHostLink("https://portal.club.org/", "portal.club.org")).toBeNull();
    expect(adminHostLink(undefined, "club.org")).toBeNull();
    expect(adminHostLink("", "club.org")).toBeNull();
  });

  it("refuses admin base URLs that are not plain HTTPS origins", () => {
    for (const base of [
      "http://app.club.org",
      "https://user@app.club.org",
      "https://app.club.org/?x=1",
      "javascript:alert(1)",
    ])
      expect(adminHostLink(base, "club.org")).toBeNull();
  });
});
