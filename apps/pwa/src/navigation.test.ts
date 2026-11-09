import type { NavigationItemResponse } from "@leonaid/api-client";
import { describe, expect, it } from "vitest";

import { activeMobileTab, mobileNavigation } from "./navigation";

const item = (
  key: string,
  href: string,
  label = key,
  surface: "web" | "pwa" = "pwa",
): NavigationItemResponse => ({ href, key, label, surface });

const acquirer: NavigationItemResponse[] = [
  item("overview-web", "/admin/", "Übersicht", "web"),
  item("overview-pwa", "/app/", "Übersicht"),
  item("tasks", "/app/tasks", "Aufgaben"),
  item("surveys", "/admin/surveys", "Umfragen"),
  item("sponsors", "/app/sponsors", "Meine Sponsoren"),
  item("commitment", "/app/commitments/new", "Bestellung erfassen"),
  item("activities", "/app/activities", "Neues"),
  item("delivery", "/app/delivery", "Auslieferung"),
];

const implemented = new Set([
  "overview-pwa",
  "sponsors",
  "commitment",
  "activities",
  "tasks",
  "surveys",
]);

const at = (pathname: string, search = "") => ({ pathname, search });

describe("mobile navigation", () => {
  it("builds the five prototype tabs from the server navigation", () => {
    const { tabs } = mobileNavigation(acquirer, implemented, at("/app/"));
    expect(
      tabs.map((tab) => [tab.key, tab.label, tab.href, tab.shortcut]),
    ).toEqual([
      ["overview-pwa", "Start", "/app/", "1"],
      ["sponsors", "Sponsoren", "/app/sponsors", "2"],
      ["sponsor-new", "Neu", "/app/sponsors?view=new", "3"],
      ["follow-ups", "Wiedervorlagen", "/app/activities?view=contacts", "4"],
      ["activities", "Neues", "/app/activities", "5"],
    ]);
    expect(tabs.filter((tab) => tab.primary).map((tab) => tab.key)).toEqual([
      "sponsor-new",
    ]);
  });

  it("keeps the fixed digits when a tab is missing", () => {
    const { tabs } = mobileNavigation(
      acquirer.filter((entry) => entry.key !== "sponsors"),
      implemented,
      at("/app/"),
    );
    expect(tabs.map((tab) => [tab.key, tab.shortcut])).toEqual([
      ["overview-pwa", "1"],
      ["follow-ups", "4"],
      ["activities", "5"],
    ]);
  });

  it("puts the other PWA entries into the sheet, unbuilt ones disabled", () => {
    const { menu } = mobileNavigation(
      acquirer,
      implemented,
      at("/app/tasks/abc"),
    );
    expect(menu.map((entry) => [entry.key, entry.href, entry.current])).toEqual(
      [
        ["tasks", "/app/tasks", true],
        ["surveys", "/admin/surveys", false],
        ["commitment", "/app/commitments/new", false],
        ["delivery", null, false],
      ],
    );
  });

  it("marks the order tile, not Neu, on order pages", () => {
    const result = mobileNavigation(
      acquirer,
      implemented,
      at("/app/commitments/abc"),
    );
    expect(result.active).toBeNull();
    expect(
      result.menu.find((entry) => entry.key === "commitment")?.current,
    ).toBe(true);
  });

  it("shows only what the server grants", () => {
    const member = [item("overview-pwa", "/app/"), item("tasks", "/app/tasks")];
    const result = mobileNavigation(member, implemented, at("/app/"));
    expect(result.tabs.map((tab) => tab.key)).toEqual(["overview-pwa"]);
    expect(result.menu.map((entry) => entry.key)).toEqual(["tasks"]);
    expect(result.active).toBe("overview-pwa");
  });

  it("drops web entries and switched-off modules", () => {
    const { menu, tabs } = mobileNavigation(
      acquirer.filter((entry) => entry.key !== "tasks"),
      implemented,
      at("/app/"),
    );
    const keys = [...tabs, ...menu].map((entry) => entry.key);
    expect(keys).not.toContain("tasks");
    expect(keys).not.toContain("overview-web");
  });

  it("names the delivery entry Meine Tour with delivery tours on", () => {
    const withDelivery = new Set([...implemented, "delivery"]);
    const label = (deliveryTours: boolean) =>
      mobileNavigation(acquirer, withDelivery, at("/app/"), {
        deliveryTours,
      }).menu.find((entry) => entry.key === "delivery")?.label;
    expect(label(false)).toBe("Auslieferung");
    expect(label(true)).toBe("Meine Tour");
  });

  it("picks the active tab from path and view", () => {
    const { tabs } = mobileNavigation(acquirer, implemented, at("/app/"));
    expect(activeMobileTab(tabs, "/app", "")).toBe("overview-pwa");
    expect(activeMobileTab(tabs, "/app/", "?action=1")).toBe("overview-pwa");
    expect(activeMobileTab(tabs, "/app/sponsors", "?status=open")).toBe(
      "sponsors",
    );
    expect(activeMobileTab(tabs, "/app/sponsors", "?view=new&action=1")).toBe(
      "sponsor-new",
    );
    expect(activeMobileTab(tabs, "/app/commitments/new", "?action=1")).toBe(
      null,
    );
    expect(
      activeMobileTab(tabs, "/app/activities", "?view=contacts&assignment=x"),
    ).toBe("follow-ups");
    expect(activeMobileTab(tabs, "/app/activities", "")).toBe("activities");
    expect(activeMobileTab(tabs, "/app/tasks", "")).toBeNull();
    expect(activeMobileTab(tabs, "/app/sponsorship", "")).toBeNull();
  });
});
