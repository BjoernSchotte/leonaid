/*
 * The driver's tour on the device (spec krapfentaxi-touren §9, D4, D14 g):
 * "Meine Tour" of today or the next delivery day, kept in the sealed device
 * store while both flags, `pwa.offline_queue` and `delivery.tours`, are on.
 * Purge: a closed window, 12 hours after a window ends, sign-out (the whole
 * store goes) and either flag off; the first of these wins. Reads shown
 * offline are kept with the tour and reach Core's first-read audit with the
 * next sync (spec §10).
 */
import {
  ApiError,
  type DeliveryDropResponse,
  type DeliveryTourStopResponse,
  type LeonAidApiClient,
  type MyTourResponse,
} from "@leonaid/api-client";

import type { CachedValue, CacheEntryInfo, CacheKind } from "./device-store";

const HOUR_MS = 3_600_000;
const DAY_MS = 24 * HOUR_MS;
/** A window's stops leave the device this long after it ends (§9). */
export const TOUR_KEEP_AFTER_END_MS = 12 * HOUR_MS;
/** Core accepts offline reads this far back (as unsent queue entries, D5). */
export const TOUR_READ_KEEP_MS = 14 * DAY_MS;
/** Core accepts a read this far ahead of its clock (phone clock drift). */
export const TOUR_READ_MAX_LEAD_MS = 5 * 60_000;
/** At most this many reads per request (MyTourReadsRequest). */
export const TOUR_READS_PER_REQUEST = 50;

export interface TourRead {
  readonly windowId: string;
  readonly readAt: string;
}

export interface CachedTour {
  /** Minimized (minimizeTour); `tour` is null once every window is purged. */
  readonly tour: MyTourResponse;
  /** When Core answered: "Offline – Stand HH:MM". */
  readonly fetchedAt: string;
  /** Offline reads not yet at Core, one per window and local day. */
  readonly reads: readonly TourRead[];
}

/** The device store as far as the tour copy needs it. */
export interface TourCacheStore {
  listCache(): Promise<CacheEntryInfo[]>;
  getCache<T>(
    kind: CacheKind,
    actionId: string,
  ): Promise<CachedValue<T> | undefined>;
  putCache(
    kind: CacheKind,
    actionId: string,
    value: unknown,
    fetchedAt: string,
  ): Promise<void>;
  deleteCache(kind: CacheKind, actionId: string): Promise<void>;
}

/** Where one action's tour lives in the device store's cache. */
export function tourCacheKey(actionId: string): readonly ["tour", string] {
  return ["tour", actionId.toLowerCase()];
}

function minimizeDrop(drop: DeliveryDropResponse): DeliveryDropResponse {
  return {
    address: drop.address ? { ...drop.address } : null,
    buyerName: drop.buyerName,
    commitmentId: drop.commitmentId,
    // The driver note stays: "Meine Tour" shows it (§5.1).
    contact: drop.contact ? { ...drop.contact } : null,
    driverName: null,
    driverUserId: drop.driverUserId,
    missedAtClosure: drop.missedAtClosure,
    orderStatus: drop.orderStatus,
    quantities: drop.quantities.map((quantity) => ({ ...quantity })),
    revision: drop.revision,
    state: drop.state,
    stateChangedAt: drop.stateChangedAt,
    // Another person's name; "Meine Tour" shows only the time.
    stateChangedByName: null,
    totalBoxes: drop.totalBoxes,
    windowId: drop.windowId,
  };
}

function minimizeStop(
  stop: DeliveryTourStopResponse,
): DeliveryTourStopResponse {
  return {
    baseRank: stop.baseRank,
    driverRank: stop.driverRank,
    drop: minimizeDrop(stop.drop),
    effectiveRank: stop.effectiveRank,
    lat: stop.lat,
    lon: stop.lon,
    newForDriver: stop.newForDriver,
  };
}

/**
 * The tour as the device keeps it: one day, no list of other days, and per
 * stop only what "Meine Tour" renders.
 */
export function minimizeTour(response: MyTourResponse): MyTourResponse {
  return {
    actionId: response.actionId,
    actionName: response.actionName,
    days: [],
    map: { ...response.map },
    startPoint: response.startPoint ? { ...response.startPoint } : null,
    timezone: response.timezone,
    tour: response.tour
      ? {
          day: response.tour.day,
          driverName: response.tour.driverName,
          driverOrderedAt: response.tour.driverOrderedAt,
          driverUserId: response.tour.driverUserId,
          revision: response.tour.revision,
          windows: response.tour.windows.map((window) => ({
            closed: window.closed,
            endsAt: window.endsAt,
            startsAt: window.startsAt,
            stops: window.stops.map(minimizeStop),
            windowId: window.windowId,
          })),
        }
      : null,
  };
}

/**
 * §9: a closed window and a window that ended more than 12 hours ago leave
 * the device. Null when no window is left.
 */
export function purgeTour(cached: CachedTour, now: Date): CachedTour | null {
  const tour = cached.tour.tour;
  if (!tour) return null;
  const windows = tour.windows.filter((window) => {
    const ends = Date.parse(window.endsAt);
    return (
      !window.closed &&
      Number.isFinite(ends) &&
      now.getTime() <= ends + TOUR_KEEP_AFTER_END_MS
    );
  });
  if (!windows.length) return null;
  if (windows.length === tour.windows.length) return cached;
  return { ...cached, tour: { ...cached.tour, tour: { ...tour, windows } } };
}

/** The calendar day of `at` in the action's zone, as Core counts reads. */
function localDay(at: Date, timeZone: string): string {
  try {
    return new Intl.DateTimeFormat("en-CA", {
      day: "2-digit",
      month: "2-digit",
      timeZone,
      year: "numeric",
    }).format(at);
  } catch {
    return at.toISOString().slice(0, 10);
  }
}

/**
 * The device showed these windows offline: one read per window and local
 * day, as Core's first-read audit keeps it; the first read of a day stays.
 */
export function noteOfflineRead(
  cached: CachedTour,
  windowIds: readonly string[],
  now: Date,
): CachedTour {
  const zone = cached.tour.timezone;
  const today = localDay(now, zone);
  const seen = new Set(
    cached.reads.map(
      (read) => `${read.windowId}@${localDay(new Date(read.readAt), zone)}`,
    ),
  );
  const added: TourRead[] = [];
  for (const windowId of new Set(windowIds)) {
    const key = `${windowId}@${today}`;
    if (seen.has(key)) continue;
    seen.add(key);
    added.push({ readAt: now.toISOString(), windowId });
  }
  return added.length
    ? { ...cached, reads: [...cached.reads, ...added] }
    : cached;
}

/** A tour copy with no window left, only reads still waiting for Core. */
function readsOnly(cached: CachedTour): CachedTour {
  return {
    ...cached,
    tour: { ...cached.tour, startPoint: null, tour: null },
  };
}

/**
 * Writes the copy after the purge rules: without a window left only waiting
 * reads stay (no stop, no address), and without those the record goes.
 */
async function storeTour(
  store: TourCacheStore,
  actionId: string,
  cached: CachedTour,
  now: Date,
): Promise<CachedTour | null> {
  const kept = purgeTour(cached, now);
  const reads = cached.reads.filter(
    (read) => now.getTime() - Date.parse(read.readAt) <= TOUR_READ_KEEP_MS,
  );
  const [kind, id] = tourCacheKey(actionId);
  if (!kept && !reads.length) {
    await store.deleteCache(kind, id);
    return null;
  }
  const next = { ...(kept ?? readsOnly(cached)), reads };
  await store.putCache(kind, id, next, next.fetchedAt);
  return kept ? next : null;
}

async function readTour(
  store: TourCacheStore,
  actionId: string,
): Promise<CachedTour | null> {
  const [kind, id] = tourCacheKey(actionId);
  const cached = await store.getCache<CachedTour>(kind, id);
  return cached?.value ?? null;
}

/**
 * The tour's default day, as Core picks it (board_day): today, else the
 * next day with stops, else the last one.
 */
function defaultDay(days: readonly string[], today: string): string | null {
  if (!days.length) return null;
  if (days.includes(today)) return today;
  return [...days].sort().find((day) => day > today) ?? days.at(-1) ?? null;
}

/**
 * Core's answer of "Meine Tour" goes to the device when it is the tour of
 * today or the next delivery day (§9); other days stay online-only. Waiting
 * reads stay with it.
 */
export async function saveTour(
  store: TourCacheStore,
  actionId: string,
  response: MyTourResponse,
  fetchedAt: Date,
): Promise<void> {
  const today = localDay(fetchedAt, response.timezone);
  const current = await readTour(store, actionId).catch(() => null);
  const own = defaultDay(response.days, today);
  if (response.tour ? response.tour.day !== own : own !== null) return;
  await storeTour(
    store,
    actionId,
    {
      fetchedAt: fetchedAt.toISOString(),
      reads: current?.reads ?? [],
      tour: minimizeTour(response),
    },
    fetchedAt,
  );
}

/**
 * The copy for an offline view, after the purge rules; the view counts as
 * a read of its windows. Null without a window to show.
 */
export async function loadOfflineTour(
  store: TourCacheStore,
  actionId: string,
  now: Date,
): Promise<CachedTour | null> {
  const cached = await readTour(store, actionId);
  if (!cached) return null;
  const kept = purgeTour(cached, now);
  const noted = kept
    ? noteOfflineRead(
        kept,
        kept.tour.tour?.windows.map((window) => window.windowId) ?? [],
        now,
      )
    : cached;
  return storeTour(store, actionId, noted, now);
}

/**
 * Applies the purge to every tour copy; `keep` names the actions the user
 * still drives for while both flags are on, null deletes every tour copy
 * (a flag off). Other cache kinds stay.
 */
export async function purgeTourCaches(
  store: TourCacheStore,
  keep: ReadonlySet<string> | null,
  now: Date = new Date(),
): Promise<void> {
  const kept = keep
    ? new Set([...keep].map((actionId) => actionId.toLowerCase()))
    : null;
  for (const entry of await store.listCache()) {
    if (entry.kind !== "tour") continue;
    if (!kept?.has(entry.actionId.toLowerCase())) {
      await store.deleteCache("tour", entry.actionId);
      continue;
    }
    const cached = await readTour(store, entry.actionId).catch(() => null);
    if (!cached) {
      // Unreadable (key changed, record edited): it cannot be shown.
      await store.deleteCache("tour", entry.actionId);
      continue;
    }
    await storeTour(store, entry.actionId, cached, now);
  }
}

/** Core cannot take it now; the reads wait for the next sync. */
function retryLater(error: unknown): boolean {
  if (!(error instanceof ApiError)) return true;
  return (
    error.status === 401 ||
    error.status === 408 ||
    error.status === 429 ||
    error.status >= 500 ||
    error.detail.code === "unexpected_response_type"
  );
}

/**
 * Sends the waiting offline reads of every tour copy (spec §10), part of the
 * sync loop. A read leaves the device once Core took it, or when Core
 * refuses it for good (out of range, flag off, no driver role any more).
 */
export async function sendTourReads(
  store: TourCacheStore,
  send: LeonAidApiClient["recordMyTourReads"],
  now: Date = new Date(),
): Promise<void> {
  for (const entry of await store.listCache()) {
    if (entry.kind !== "tour") continue;
    const cached = await readTour(store, entry.actionId).catch(() => null);
    if (!cached?.reads.length) continue;
    // Core refuses a whole batch for one read out of its range, so such a
    // read leaves the device unsent: older than 14 days, or ahead of the
    // clock beyond the drift (noted while the device clock was wrong).
    const due = cached.reads.filter((read) => readSendable(read, now));
    const done = new Set<string>(
      cached.reads.filter((read) => !due.includes(read)).map(readKey),
    );
    let stop = false;
    for (
      let index = 0;
      index < due.length && !stop;
      index += TOUR_READS_PER_REQUEST
    ) {
      const batch = due.slice(index, index + TOUR_READS_PER_REQUEST);
      try {
        await send(entry.actionId, {
          reads: batch.map((read) => ({ ...read })),
        });
      } catch (error) {
        if (retryLater(error)) {
          stop = true;
          continue;
        }
      }
      for (const read of batch) done.add(readKey(read));
    }
    if (!done.size) continue;
    // Read again: the page may have noted a read meanwhile.
    const latest = await readTour(store, entry.actionId).catch(() => null);
    if (!latest) continue;
    await storeTour(
      store,
      entry.actionId,
      {
        ...latest,
        reads: latest.reads.filter((read) => !done.has(readKey(read))),
      },
      now,
    );
  }
}

function readSendable(read: TourRead, now: Date): boolean {
  const at = Date.parse(read.readAt);
  return (
    Number.isFinite(at) &&
    now.getTime() - at <= TOUR_READ_KEEP_MS &&
    at - now.getTime() <= TOUR_READ_MAX_LEAD_MS
  );
}

function readKey(read: TourRead): string {
  return `${read.windowId}@${read.readAt}`;
}
