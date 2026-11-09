/**
 * Pure client helpers for delivery tours: ordering within a window, the
 * nearest-next suggestion, navigation/tel links and the window time hint.
 * No I/O, no React.
 */

export type TourPoint = {
  readonly id: string;
  readonly windowId: string;
  readonly lat: number | null;
  readonly lon: number | null;
};

type Coord = { readonly lat: number; readonly lon: number };

const hasCoord = (p: {
  lat: number | null;
  lon: number | null;
}): p is Coord & { lat: number; lon: number } =>
  p.lat !== null && p.lon !== null;

/** Moves `id` one step inside its window. Edge moves return an unchanged copy. */
export function moveStop(
  ids: readonly string[],
  id: string,
  direction: -1 | 1,
  windowOf: (id: string) => string,
): string[] {
  const from = ids.indexOf(id);
  const to = from + direction;
  const next = ids[to];
  if (from < 0 || next === undefined || windowOf(next) !== windowOf(id)) {
    return [...ids];
  }
  const result = [...ids];
  result[from] = next;
  result[to] = id;
  return result;
}

/** Drops `id` before/after `targetId`. A target in another window does nothing. */
export function placeStop(
  ids: readonly string[],
  id: string,
  targetId: string,
  side: "before" | "after",
  windowOf: (id: string) => string,
): string[] {
  if (
    id === targetId ||
    !ids.includes(id) ||
    !ids.includes(targetId) ||
    windowOf(id) !== windowOf(targetId)
  ) {
    return [...ids];
  }
  const rest = ids.filter((candidate) => candidate !== id);
  const at = rest.indexOf(targetId) + (side === "after" ? 1 : 0);
  rest.splice(at, 0, id);
  return rest;
}

/**
 * A local order (a move that is saving) kept to the tour's current stops:
 * gone stops drop out, a stop added since goes to the end of its own
 * window, not of the whole tour. Windows follow `base`.
 */
export function reconcileOrder(
  local: readonly string[],
  base: readonly string[],
  windowOf: (id: string) => string,
): string[] {
  const windows = [...new Set(base.map(windowOf))];
  return windows.flatMap((window) => {
    const current = base.filter((id) => windowOf(id) === window);
    const known = local.filter((id) => current.includes(id));
    return [...known, ...current.filter((id) => !known.includes(id))];
  });
}

const EARTH_RADIUS_KM = 6371.0088;
const rad = (deg: number) => (deg * Math.PI) / 180;

export function haversineKm(a: Coord, b: Coord): number {
  const dLat = rad(b.lat - a.lat);
  const dLon = rad(b.lon - a.lon);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Windows in order of first appearance. */
function groupByWindow(points: readonly TourPoint[]): TourPoint[][] {
  const groups = new Map<string, TourPoint[]>();
  for (const point of points) {
    const group = groups.get(point.windowId);
    if (group) group.push(point);
    else groups.set(point.windowId, [point]);
  }
  return [...groups.values()];
}

function furthestFromCentroid(points: readonly Coord[]): Coord | null {
  if (points.length === 0) return null;
  const centroid = {
    lat: points.reduce((sum, p) => sum + p.lat, 0) / points.length,
    lon: points.reduce((sum, p) => sum + p.lon, 0) / points.length,
  };
  let best = points[0];
  let bestDistance = -1;
  for (const point of points) {
    const distance = haversineKm(centroid, point);
    if (distance > bestDistance) {
      best = point;
      bestDistance = distance;
    }
  }
  return best ?? null;
}

/**
 * Greedy nearest-next order per window. The first window starts at `start`
 * (or the stop furthest from the centroid); later windows start at the last
 * placed stop. Stops without coordinates keep their order at the window end.
 */
export function nearestNextOrder(
  points: readonly TourPoint[],
  start: Coord | null,
): string[] {
  const located = points.filter(hasCoord) as (TourPoint & Coord)[];
  let from: Coord | null = start ?? furthestFromCentroid(located);
  const result: string[] = [];
  for (const group of groupByWindow(points)) {
    const remaining = group.filter(hasCoord) as (TourPoint & Coord)[];
    const unlocated = group.filter((p) => !hasCoord(p));
    while (remaining.length > 0) {
      let pick = 0;
      if (from) {
        let bestDistance = Infinity;
        remaining.forEach((candidate, index) => {
          const distance = haversineKm(from as Coord, candidate);
          if (distance < bestDistance) {
            bestDistance = distance;
            pick = index;
          }
        });
      }
      const [chosen] = remaining.splice(pick, 1);
      if (!chosen) break;
      result.push(chosen.id);
      from = { lat: chosen.lat, lon: chosen.lon };
    }
    for (const point of unlocated) result.push(point.id);
  }
  return result;
}

/** True when at least 2 stops of one window have coordinates. */
export function canSuggestOrder(points: readonly TourPoint[]): boolean {
  return groupByWindow(points).some(
    (group) => group.filter(hasCoord).length >= 2,
  );
}

/** Length of the tour in km, following `points` in the given order. */
export function tourLengthKm(
  points: readonly TourPoint[],
  start: Coord | null,
): number {
  let total = 0;
  let from: Coord | null = start;
  for (const point of points) {
    if (!hasCoord(point)) continue;
    const here = { lat: point.lat, lon: point.lon };
    if (from) total += haversineKm(from, here);
    from = here;
  }
  return total;
}

export type DevicePlatform = "android" | "ios" | "other";

export function devicePlatform(userAgent: string): DevicePlatform {
  if (/android/i.test(userAgent)) return "android";
  if (/iphone|ipad|ipod/i.test(userAgent)) return "ios";
  return "other";
}

export function navigationHref(
  stop: {
    readonly lat: number | null;
    readonly lon: number | null;
    readonly address: string;
  },
  platform: DevicePlatform,
): string {
  const address = encodeURIComponent(stop.address);
  const located = hasCoord(stop);
  switch (platform) {
    case "android":
      return located
        ? `geo:${stop.lat},${stop.lon}?q=${address}`
        : `geo:0,0?q=${address}`;
    case "ios":
      return located
        ? `maps://?daddr=${stop.lat},${stop.lon}`
        : `maps://?daddr=${address}`;
    default:
      return located
        ? `https://www.openstreetmap.org/directions?to=${stop.lat},${stop.lon}`
        : `https://www.openstreetmap.org/search?query=${address}`;
  }
}

/** `tel:` link for the first non-empty number, or null. */
export function callHref(
  deliveryPhone: string | null,
  orderPhone: string | null,
): string | null {
  for (const raw of [deliveryPhone, orderPhone]) {
    const number = raw?.trim().replace(/[\s/().]/g, "");
    if (number) return `tel:${number}`;
  }
  return null;
}

export type WindowHint =
  | { readonly kind: "upcoming" }
  | { readonly kind: "running"; readonly minutesLeft: number }
  | { readonly kind: "ended" };

export function windowHint(
  startsAt: string,
  endsAt: string,
  now: Date,
): WindowHint {
  const start = Date.parse(startsAt);
  const end = Date.parse(endsAt);
  const at = now.getTime();
  if (at >= end) return { kind: "ended" };
  if (at < start) return { kind: "upcoming" };
  return { kind: "running", minutesLeft: Math.ceil((end - at) / 60_000) };
}

/** "08–10 · noch 35 min" while running; otherwise the label alone. */
export function windowHintLabel(label: string, hint: WindowHint): string {
  return hint.kind === "running"
    ? `${label} · noch ${hint.minutesLeft} min`
    : label;
}

/** OpenStreetMap at the pin, or an OSM search for the address (spec §7.1, D15). */
export function osmHref(stop: {
  readonly lat: number | null;
  readonly lon: number | null;
  readonly address: string;
}): string {
  return hasCoord(stop)
    ? `https://www.openstreetmap.org/?mlat=${stop.lat}&mlon=${stop.lon}#map=18/${stop.lat}/${stop.lon}`
    : `https://www.openstreetmap.org/search?query=${encodeURIComponent(stop.address)}`;
}
