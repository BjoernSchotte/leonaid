import {
  callHref,
  canSuggestOrder,
  devicePlatform,
  haversineKm,
  moveStop,
  navigationHref,
  nearestNextOrder,
  placeStop,
  tourLengthKm,
  windowHint,
  windowHintLabel,
  type TourPoint,
} from "@leonaid/features";
import { describe, expect, it } from "vitest";

const w = (id: string) => (id === "c" ? "w2" : "w1");

describe("moveStop / placeStop", () => {
  it("swaps within a window", () => {
    expect(moveStop(["a", "b", "c"], "b", -1, w)).toEqual(["b", "a", "c"]);
  });
  it("does nothing at the list edge or across a window edge", () => {
    expect(moveStop(["a", "b", "c"], "b", 1, w)).toEqual(["a", "b", "c"]);
    expect(moveStop(["a", "b", "c"], "a", -1, w)).toEqual(["a", "b", "c"]);
  });
  it("places before/after a target in the same window only", () => {
    expect(placeStop(["a", "b", "c"], "a", "b", "after", w)).toEqual([
      "b",
      "a",
      "c",
    ]);
    expect(placeStop(["a", "b", "c"], "b", "a", "before", w)).toEqual([
      "b",
      "a",
      "c",
    ]);
    expect(placeStop(["a", "b", "c"], "a", "c", "after", w)).toEqual([
      "a",
      "b",
      "c",
    ]);
  });
});

const pt = (id: string, lon: number | null, windowId = "w1"): TourPoint => ({
  id,
  windowId,
  lat: lon === null ? null : 48,
  lon,
});

describe("nearestNextOrder", () => {
  const shuffled = [pt("b", 11.1), pt("c", 11.2), pt("a", 11.0)];
  it("starts at the given start point", () => {
    expect(nearestNextOrder(shuffled, { lat: 48, lon: 11.0 })).toEqual([
      "a",
      "b",
      "c",
    ]);
  });
  it("starts at the outlier without a start", () => {
    const points = [
      pt("a", 11.0),
      pt("b", 11.01),
      pt("c", 11.02),
      pt("d", 11.5),
    ];
    expect(nearestNextOrder(points, null)[0]).toBe("d");
  });
  it("keeps unlocated stops at the end of their window and chains windows", () => {
    const points = [
      pt("x", null),
      pt("b", 11.1),
      pt("a", 11.0),
      pt("d", 11.3, "w2"),
      pt("c", 11.2, "w2"),
    ];
    expect(nearestNextOrder(points, { lat: 48, lon: 11.0 })).toEqual([
      "a",
      "b",
      "x",
      "c",
      "d",
    ]);
  });
  it("canSuggestOrder needs 2 located stops in one window", () => {
    expect(canSuggestOrder([pt("a", 11), pt("b", 11.1, "w2")])).toBe(false);
    expect(canSuggestOrder([pt("a", 11), pt("b", 11.1)])).toBe(true);
  });
  it("measures length", () => {
    const km = haversineKm({ lat: 48, lon: 11 }, { lat: 48, lon: 11.1 });
    expect(km).toBeGreaterThan(7);
    expect(km).toBeLessThan(8);
    expect(tourLengthKm([pt("a", 11), pt("b", 11.1)], null)).toBeCloseTo(km);
  });
});

describe("links", () => {
  const stop = { lat: 48.1, lon: 11.5, address: "Hauptstr. 1, 80331 München" };
  const q = encodeURIComponent(stop.address);
  it("builds navigation links per platform", () => {
    expect(navigationHref(stop, "android")).toBe(`geo:48.1,11.5?q=${q}`);
    expect(navigationHref(stop, "ios")).toBe("maps://?daddr=48.1,11.5");
    expect(navigationHref(stop, "other")).toBe(
      "https://www.openstreetmap.org/directions?to=48.1,11.5",
    );
  });
  it("falls back to the address without coordinates", () => {
    const bare = { lat: null, lon: null, address: stop.address };
    expect(navigationHref(bare, "android")).toBe(`geo:0,0?q=${q}`);
    expect(navigationHref(bare, "ios")).toBe(`maps://?daddr=${q}`);
    expect(navigationHref(bare, "other")).toBe(
      `https://www.openstreetmap.org/search?query=${q}`,
    );
  });
  it("detects platform", () => {
    expect(devicePlatform("Mozilla/5.0 (Linux; Android 14)")).toBe("android");
    expect(devicePlatform("Mozilla/5.0 (iPhone; CPU iPhone OS 17)")).toBe(
      "ios",
    );
    expect(devicePlatform("Mozilla/5.0 (X11; Linux x86_64)")).toBe("other");
  });
  it("builds tel links", () => {
    expect(callHref(" ", "+49 (89) 123/45")).toBe("tel:+498912345");
    expect(callHref("089.1", "2")).toBe("tel:0891");
    expect(callHref(null, "")).toBeNull();
  });
});

describe("windowHint", () => {
  const s = "2026-11-11T07:00:00Z";
  const e = "2026-11-11T09:00:00Z";
  it("reports running, upcoming and ended", () => {
    const hint = windowHint(s, e, new Date("2026-11-11T08:35:00Z"));
    expect(hint).toEqual({ kind: "running", minutesLeft: 25 });
    expect(windowHintLabel("08–10", hint)).toBe("08–10 · noch 25 min");
    expect(windowHint(s, e, new Date("2026-11-11T06:00:00Z"))).toEqual({
      kind: "upcoming",
    });
    const ended = windowHint(s, e, new Date("2026-11-11T09:00:00Z"));
    expect(ended).toEqual({ kind: "ended" });
    expect(windowHintLabel("08–10", ended)).toBe("08–10");
  });
});
