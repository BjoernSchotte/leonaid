import { navigationZones, zoneForNavKey } from "@leonaid/features";

describe("navigation zones", () => {
  it("gives every zone a unique g letter and server key", () => {
    const letters = navigationZones.map((zone) => zone.key);
    const navKeys = navigationZones.map((zone) => zone.navKey);
    expect(new Set(letters).size).toBe(letters.length);
    expect(new Set(navKeys).size).toBe(navKeys.length);
    for (const letter of letters) expect(letter).toMatch(/^[a-z]$/);
  });

  it("keeps the approved letter map", () => {
    expect(
      Object.fromEntries(
        navigationZones.map((zone) => [zone.key, zone.navKey]),
      ),
    ).toEqual({
      d: "overview-web",
      a: "actions",
      b: "orders",
      l: "delivery",
      r: "invoices",
      t: "tasks",
      u: "surveys",
      e: "inbox",
      x: "materials",
      w: "knowledge",
      f: "activities",
      m: "members",
      k: "microsite",
      j: "legal",
      s: "system",
      p: "acquisition-app",
      q: "acquisition-web",
      o: "public",
    });
  });

  it("looks zones up by server navigation key", () => {
    expect(zoneForNavKey("orders")?.label).toBe("Bestellungen");
    expect(zoneForNavKey("unknown")).toBeUndefined();
  });
});
