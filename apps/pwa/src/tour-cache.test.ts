// @vitest-environment jsdom
/*
 * The driver's tour on the device (spec krapfentaxi-touren §9, §10, D14 g):
 * minimization, the purge rules, the flag-off and sign-out wipes and the
 * offline reads with their sync. The device store is an in-memory stand-in
 * with the same cache contract; IndexedDB itself runs in the browser specs.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  type DeliveryTourWindowResponse,
  type MyTourReadsRequest,
  type MyTourResponse,
} from "@leonaid/api-client";
import {
  databaseName,
  forgetDevice,
  loadOfflineTour,
  minimizeTour,
  noteOfflineRead,
  purgeTour,
  purgeTourCaches,
  saveTour,
  sendTourReads,
  setActiveDeviceUser,
  tourCacheKey,
  type CacheEntryInfo,
  type CacheKind,
  type CachedTour,
  type CachedValue,
  type TourCacheStore,
} from "@leonaid/features/offline";

const ACTION = "20000000-0000-4000-8000-000000000001";
const OTHER_ACTION = "20000000-0000-4000-8000-000000000002";
const DRIVER = "10000000-0000-4000-8000-000000000007";
const OPEN_WINDOW = "70000000-0000-4000-8000-000000000001";
const CLOSED_WINDOW = "70000000-0000-4000-8000-000000000002";
const HOUR = 3_600_000;
// Saturday 5 Dec 2026, 09:00 in Berlin.
const NOW = new Date("2026-12-05T08:00:00Z");

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

function window_(
  windowId: string,
  startsAt: string,
  endsAt: string,
  closed = false,
): DeliveryTourWindowResponse {
  return {
    closed,
    endsAt,
    startsAt,
    stops: [
      {
        baseRank: 1,
        driverRank: null,
        drop: {
          address: {
            city: "Bad Tölz",
            postalCode: "83646",
            recipientName: "Familie Huber",
            streetLine1: "Marktstraße 1",
          },
          buyerName: "Anna Huber",
          commitmentId: `${windowId.slice(0, 30)}aaaaaa`,
          contact: {
            driverNote: "Hund im Hof, bitte klingeln",
            name: "Anna Huber",
            phone: "+49 8041 1234",
          },
          driverName: "Fahrer Franz",
          driverUserId: DRIVER,
          missedAtClosure: false,
          orderStatus: null,
          quantities: [{ quantity: 2, unit: "box" }],
          revision: 3,
          state: "open",
          stateChangedAt: null,
          stateChangedByName: "Planerin Petra",
          totalBoxes: 2,
          windowId,
        },
        effectiveRank: 1,
        lat: 47.76,
        lon: 11.56,
        newForDriver: false,
      },
    ],
    windowId,
  };
}

function response(
  windows: DeliveryTourWindowResponse[],
  { day = "2026-12-05", days = ["2026-12-05", "2026-12-12"] } = {},
): MyTourResponse {
  return {
    actionId: ACTION,
    actionName: "Krapfentaxi 2026",
    days,
    map: { attribution: "© OSM", tileUrl: "/tiles/{z}/{x}/{y}.png" },
    startPoint: {
      address: "Am Schloßplatz 1",
      label: "Vereinsheim",
      lat: 47.7,
      locating: false,
      lon: 11.5,
    },
    timezone: "Europe/Berlin",
    tour: {
      day,
      driverName: "Fahrer Franz",
      driverOrderedAt: null,
      driverUserId: DRIVER,
      revision: "r1",
      windows,
    },
  };
}

const openWindow = () =>
  window_(OPEN_WINDOW, "2026-12-05T08:00:00Z", "2026-12-05T10:00:00Z");
const closedWindow = () =>
  window_(CLOSED_WINDOW, "2026-12-05T06:00:00Z", "2026-12-05T08:00:00Z", true);

function cached(
  windows: DeliveryTourWindowResponse[],
  reads: CachedTour["reads"] = [],
): CachedTour {
  return {
    fetchedAt: NOW.toISOString(),
    reads,
    tour: minimizeTour(response(windows)),
  };
}

/** The device store's cache, in memory, with the same contract. */
class MemoryStore implements TourCacheStore {
  readonly records = new Map<
    string,
    { kind: CacheKind; actionId: string; value: unknown; fetchedAt: string }
  >();

  async listCache(): Promise<CacheEntryInfo[]> {
    return [...this.records.values()].map(({ actionId, fetchedAt, kind }) => ({
      actionId,
      fetchedAt,
      kind,
    }));
  }

  async getCache<T>(
    kind: CacheKind,
    actionId: string,
  ): Promise<CachedValue<T> | undefined> {
    const record = this.records.get(`${kind}:${actionId}`);
    return record
      ? {
          fetchedAt: record.fetchedAt,
          // A copy, as IndexedDB returns one.
          value: structuredClone(record.value) as T,
        }
      : undefined;
  }

  async putCache(
    kind: CacheKind,
    actionId: string,
    value: unknown,
    fetchedAt: string,
  ) {
    this.records.set(`${kind}:${actionId}`, {
      actionId,
      fetchedAt,
      kind,
      value: structuredClone(value),
    });
  }

  async deleteCache(kind: CacheKind, actionId: string) {
    this.records.delete(`${kind}:${actionId}`);
  }

  tour(actionId = ACTION): CachedTour | undefined {
    const [kind, id] = tourCacheKey(actionId);
    return this.records.get(`${kind}:${id}`)?.value as CachedTour | undefined;
  }
}

describe("minimizeTour", () => {
  it("drops the day list and other people's names, keeps the driver note", () => {
    const minimized = minimizeTour(response([openWindow()]));
    expect(minimized.days).toEqual([]);
    const drop = minimized.tour!.windows[0].stops[0].drop;
    expect(drop.stateChangedByName).toBeNull();
    expect(drop.driverName).toBeNull();
    expect(drop.contact).toEqual({
      driverNote: "Hund im Hof, bitte klingeln",
      name: "Anna Huber",
      phone: "+49 8041 1234",
    });
    expect(drop.address?.streetLine1).toBe("Marktstraße 1");
  });
});

describe("purgeTour (§9)", () => {
  it("purge drops a closed window and keeps the open one", () => {
    const kept = purgeTour(cached([closedWindow(), openWindow()]), NOW);
    expect(kept?.tour.tour?.windows.map((window) => window.windowId)).toEqual([
      OPEN_WINDOW,
    ]);
  });

  it("purge drops a window 12 h after its end", () => {
    const tour = cached([openWindow()]);
    const end = Date.parse("2026-12-05T10:00:00Z");
    expect(purgeTour(tour, new Date(end + 12 * HOUR))).not.toBeNull();
    expect(purgeTour(tour, new Date(end + 12 * HOUR + 1))).toBeNull();
  });

  it("purge returns null when nothing is left", () => {
    expect(purgeTour(cached([closedWindow()]), NOW)).toBeNull();
    expect(purgeTour(cached([]), NOW)).toBeNull();
  });
});

describe("saveTour", () => {
  it("keeps today's tour, minimized, and leaves other days online-only", async () => {
    const store = new MemoryStore();
    await saveTour(store, ACTION, response([openWindow()]), NOW);
    expect(store.tour()?.tour.days).toEqual([]);
    expect(store.tour()?.fetchedAt).toBe(NOW.toISOString());

    const later = new MemoryStore();
    await saveTour(
      later,
      ACTION,
      response([openWindow()], { day: "2026-12-12" }),
      NOW,
    );
    expect(later.tour()).toBeUndefined();
  });

  it("keeps the next delivery day before the first one", async () => {
    const store = new MemoryStore();
    const next = window_(
      OPEN_WINDOW,
      "2026-12-12T08:00:00Z",
      "2026-12-12T10:00:00Z",
    );
    await saveTour(
      store,
      ACTION,
      response([next], { day: "2026-12-12", days: ["2026-12-12"] }),
      NOW,
    );
    expect(store.tour()?.tour.tour?.day).toBe("2026-12-12");
  });

  it("keeps waiting reads when Core's answer replaces the tour", async () => {
    const store = new MemoryStore();
    const read = { readAt: NOW.toISOString(), windowId: OPEN_WINDOW };
    await store.putCache(
      ...tourCacheKey(ACTION),
      cached([openWindow()], [read]),
      NOW.toISOString(),
    );
    await saveTour(store, ACTION, response([openWindow()]), NOW);
    expect(store.tour()?.reads).toEqual([read]);
  });
});

describe("flag off and sign-out", () => {
  it("flag off deletes the tour cache", async () => {
    const store = new MemoryStore();
    await store.putCache("board", ACTION, { workItems: [] }, NOW.toISOString());
    await saveTour(store, ACTION, response([openWindow()]), NOW);
    expect(store.tour()).toBeDefined();
    await purgeTourCaches(store, null, NOW);
    expect(store.tour()).toBeUndefined();
    // Only the tour: the acquirer's board stays.
    expect(store.records.has(`board:${ACTION}`)).toBe(true);
  });

  it("deletes the tour copy of an action the user no longer drives for", async () => {
    const store = new MemoryStore();
    await saveTour(store, ACTION, response([openWindow()]), NOW);
    await saveTour(
      store,
      OTHER_ACTION,
      { ...response([openWindow()]), actionId: OTHER_ACTION },
      NOW,
    );
    await purgeTourCaches(store, new Set([OTHER_ACTION.toUpperCase()]), NOW);
    expect(store.tour(ACTION)).toBeUndefined();
    expect(store.tour(OTHER_ACTION)).toBeDefined();
  });

  it("sign-out deletes the tour cache", async () => {
    // The tour copy lives in the user's database; sign-out deletes it whole
    // (and the device's active user's), as for the read cache and queue.
    const deleted: string[] = [];
    vi.stubGlobal("indexedDB", {
      databases: async () => [],
      deleteDatabase: (name: string) => {
        deleted.push(name);
        const request = {} as IDBOpenDBRequest;
        queueMicrotask(() => request.onsuccess?.(new Event("success")));
        return request;
      },
    });
    setActiveDeviceUser(DRIVER);
    await forgetDevice(DRIVER);
    expect(deleted).toEqual([databaseName(DRIVER)]);
    expect(window.localStorage.length).toBe(0);
  });
});

describe("offline reads (§10)", () => {
  it("offline read is recorded once per window and day", () => {
    let tour = cached([closedWindow(), openWindow()]);
    tour = noteOfflineRead(tour, [OPEN_WINDOW, CLOSED_WINDOW], NOW);
    tour = noteOfflineRead(
      tour,
      [OPEN_WINDOW, OPEN_WINDOW],
      new Date(NOW.getTime() + 2 * HOUR),
    );
    expect(tour.reads).toEqual([
      { readAt: NOW.toISOString(), windowId: OPEN_WINDOW },
      { readAt: NOW.toISOString(), windowId: CLOSED_WINDOW },
    ]);
    // The next day in Berlin (00:30 local) is a new read.
    const nextDay = new Date("2026-12-05T23:30:00Z");
    tour = noteOfflineRead(tour, [OPEN_WINDOW], nextDay);
    expect(tour.reads).toHaveLength(3);
    expect(tour.reads[2]).toEqual({
      readAt: nextDay.toISOString(),
      windowId: OPEN_WINDOW,
    });
  });

  it("an offline view applies the purge and notes the read", async () => {
    const store = new MemoryStore();
    await store.putCache(
      ...tourCacheKey(ACTION),
      cached([closedWindow(), openWindow()]),
      NOW.toISOString(),
    );
    const shown = await loadOfflineTour(store, ACTION, NOW);
    expect(shown?.tour.tour?.windows.map((window) => window.windowId)).toEqual([
      OPEN_WINDOW,
    ]);
    expect(store.tour()?.reads).toEqual([
      { readAt: NOW.toISOString(), windowId: OPEN_WINDOW },
    ]);
  });

  it("keeps waiting reads but no stop once every window is purged", async () => {
    const store = new MemoryStore();
    const read = { readAt: NOW.toISOString(), windowId: OPEN_WINDOW };
    await store.putCache(
      ...tourCacheKey(ACTION),
      cached([openWindow()], [read]),
      NOW.toISOString(),
    );
    const late = new Date(Date.parse("2026-12-05T10:00:00Z") + 13 * HOUR);
    expect(await loadOfflineTour(store, ACTION, late)).toBeNull();
    expect(store.tour()?.tour.tour).toBeNull();
    expect(store.tour()?.tour.startPoint).toBeNull();
    expect(store.tour()?.reads).toEqual([read]);
  });

  it("sends waiting reads with the sync, in batches of 50, then forgets them", async () => {
    const store = new MemoryStore();
    const reads = Array.from({ length: 60 }, (_, index) => ({
      readAt: new Date(NOW.getTime() - index * 60_000).toISOString(),
      windowId: OPEN_WINDOW,
    }));
    await store.putCache(
      ...tourCacheKey(ACTION),
      cached([openWindow()], reads),
      NOW.toISOString(),
    );
    const sent: MyTourReadsRequest[] = [];
    await sendTourReads(
      store,
      async (actionId, body) => {
        expect(actionId).toBe(ACTION);
        sent.push(body);
      },
      NOW,
    );
    expect(sent.map((body) => body.reads.length)).toEqual([50, 10]);
    expect(store.tour()?.reads).toEqual([]);
    expect(store.tour()?.tour.tour).not.toBeNull();
  });

  it("keeps reads without network and drops reads Core refuses for good", async () => {
    const store = new MemoryStore();
    const read = { readAt: NOW.toISOString(), windowId: OPEN_WINDOW };
    await store.putCache(
      ...tourCacheKey(ACTION),
      cached([openWindow()], [read]),
      NOW.toISOString(),
    );
    await sendTourReads(
      store,
      async () => {
        throw new TypeError("Failed to fetch");
      },
      NOW,
    );
    expect(store.tour()?.reads).toEqual([read]);
    await sendTourReads(
      store,
      async () => {
        throw new ApiError(422, {
          code: "tour_read_out_of_range",
          message: "",
          requestId: "",
        });
      },
      NOW,
    );
    expect(store.tour()?.reads).toEqual([]);
  });

  it("a batch refused with 422 goes again read by read; only the refused read is dropped", async () => {
    const store = new MemoryStore();
    // Core's clock is behind the device's: the device cannot tell.
    const ahead = { readAt: NOW.toISOString(), windowId: CLOSED_WINDOW };
    const good = [0, 1].map((minutes) => ({
      readAt: new Date(NOW.getTime() - (minutes + 1) * 60_000).toISOString(),
      windowId: OPEN_WINDOW,
    }));
    await store.putCache(
      ...tourCacheKey(ACTION),
      cached([openWindow()], [...good, ahead]),
      NOW.toISOString(),
    );
    const taken: MyTourReadsRequest["reads"][number][] = [];
    const outOfRange = new ApiError(422, {
      code: "tour_read_out_of_range",
      message: "",
      requestId: "",
    });
    await sendTourReads(
      store,
      async (_actionId, body) => {
        if (body.reads.some((read) => read.readAt === ahead.readAt)) {
          throw outOfRange;
        }
        taken.push(...body.reads);
      },
      NOW,
    );
    expect(taken).toEqual(good);
    expect(store.tour()?.reads).toEqual([]);
  });

  it("reads sent one by one stop at a network error and keep the rest", async () => {
    const store = new MemoryStore();
    const reads = [0, 1, 2].map((minutes) => ({
      readAt: new Date(NOW.getTime() - minutes * 60_000).toISOString(),
      windowId: OPEN_WINDOW,
    }));
    await store.putCache(
      ...tourCacheKey(ACTION),
      cached([openWindow()], reads),
      NOW.toISOString(),
    );
    let calls = 0;
    await sendTourReads(
      store,
      async () => {
        calls += 1;
        if (calls === 1) {
          throw new ApiError(422, {
            code: "tour_read_out_of_range",
            message: "",
            requestId: "",
          });
        }
        if (calls === 3) throw new TypeError("Failed to fetch");
      },
      NOW,
    );
    // Batch refused, first read taken, network gone at the second.
    expect(calls).toBe(3);
    expect(store.tour()?.reads).toEqual(reads.slice(1));
  });

  it("drops a read far ahead of the clock so it never sinks the batch", async () => {
    const store = new MemoryStore();
    const good = { readAt: NOW.toISOString(), windowId: OPEN_WINDOW };
    const drift = {
      readAt: new Date(NOW.getTime() + 4 * 60_000).toISOString(),
      windowId: CLOSED_WINDOW,
    };
    const ahead = {
      readAt: new Date(NOW.getTime() + 6 * 60_000).toISOString(),
      windowId: OPEN_WINDOW,
    };
    await store.putCache(
      ...tourCacheKey(ACTION),
      cached([openWindow()], [good, ahead, drift]),
      NOW.toISOString(),
    );
    const sent: MyTourReadsRequest[] = [];
    await sendTourReads(
      store,
      async (_actionId, body) => {
        sent.push(body);
      },
      NOW,
    );
    expect(sent).toEqual([{ reads: [good, drift] }]);
    expect(store.tour()?.reads).toEqual([]);
  });

  it("does not send reads older than 14 days", async () => {
    const store = new MemoryStore();
    const old = {
      readAt: new Date(NOW.getTime() - 15 * 24 * HOUR).toISOString(),
      windowId: OPEN_WINDOW,
    };
    await store.putCache(
      ...tourCacheKey(ACTION),
      cached([openWindow()], [old]),
      NOW.toISOString(),
    );
    const send = vi.fn(async () => undefined);
    await sendTourReads(store, send, NOW);
    expect(send).not.toHaveBeenCalled();
    expect(store.tour()?.reads).toEqual([]);
  });
});
