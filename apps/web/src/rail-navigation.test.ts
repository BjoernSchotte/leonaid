import type { NavigationItemResponse } from "@leonaid/api-client";
import { railCampaigns, railNavigation } from "@leonaid/features";

const item = (
  key: string,
  label: string,
  href: string,
  surface: "web" | "pwa" = "web",
): NavigationItemResponse => ({ key, label, href, surface });

describe("rail navigation", () => {
  const server = [
    item("overview-web", "Übersicht", "/admin/"),
    item("overview-pwa", "Übersicht", "/app/", "pwa"),
    item("system", "System", "/admin/system"),
    item("privacy", "Datenschutz", "/admin/privacy"),
    item("legal", "Organisation & Recht", "/admin/legal"),
    item("tasks", "Aufgaben", "/admin/tasks"),
    item("orders", "Bestellungen", "/admin/orders"),
    item("polls", "Abstimmungen", "/admin/polls"),
    item("members", "Mitglieder", "/admin/members"),
  ];

  it("shows only the web items the server returned, grouped in zone order", () => {
    const rail = railNavigation(server, ["tasks", "polls"]);
    expect(rail.map((entry) => [entry.group, entry.key])).toEqual([
      ["Arbeit", "overview-web"],
      ["Arbeit", "orders"],
      ["Module", "tasks"],
      ["Module", "polls"],
      ["Verwaltung", "members"],
      ["Verwaltung", "legal"],
      ["Verwaltung", "privacy"],
      ["Verwaltung", "system"],
    ]);
  });

  it("uses zone labels and letters, server labels for unknown items", () => {
    const rail = railNavigation(server, ["tasks", "polls"]);
    const byKey = new Map(rail.map((entry) => [entry.key, entry]));
    expect(byKey.get("legal")).toMatchObject({
      label: "Rechtliches",
      goKey: "j",
      href: "/admin/legal",
    });
    expect(byKey.get("privacy")).toMatchObject({
      label: "Datenschutz",
      goKey: undefined,
    });
    expect(byKey.get("polls")).toMatchObject({
      label: "Abstimmungen",
      goKey: undefined,
    });
  });

  it("drops switched-off modules because the server omits them", () => {
    const rail = railNavigation(
      server.filter((entry) => entry.key !== "tasks"),
      ["tasks", "polls"],
    );
    expect(rail.some((entry) => entry.key === "tasks")).toBe(false);
  });

  it("lists each campaign once with its roles", () => {
    expect(
      railCampaigns({
        actionMemberships: [
          {
            actionId: "a1",
            actionName: "Krapfentaxi",
            role: "charity_admin",
            roleLabel: "Charity-Admin",
          },
          {
            actionId: "a1",
            actionName: "Krapfentaxi",
            role: "driver",
            roleLabel: "Fahrer",
          },
          {
            actionId: "a2",
            actionName: "Weihnachtsmarkt",
            role: "acquirer",
            roleLabel: "Akquise",
          },
        ],
      }),
    ).toEqual([
      { id: "a1", name: "Krapfentaxi", hint: "Charity-Admin · Fahrer" },
      { id: "a2", name: "Weihnachtsmarkt", hint: "Akquise" },
    ]);
  });
});
