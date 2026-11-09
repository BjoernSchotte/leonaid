// @vitest-environment jsdom
/*
 * Flag off removes the driver's tour copy (krapfentaxi-touren §9, D14 g)
 * through the real wiring: the online start (prepareDevice) and, mid-
 * session, useTourCachePurge on Core's answer. A flag only assumed
 * (offline) deletes nothing. The device store is an in-memory stand-in;
 * IndexedDB itself runs in the browser specs.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CurrentIdentityResponse,
  FeatureFlagEvaluationListResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import { FEATURE_FLAGS, FeatureFlagProvider } from "@leonaid/features";
import {
  IDENTITY_META,
  OfflineRuntimeContext,
  useTourCachePurge,
  type CacheEntryInfo,
  type CacheKind,
  type CachedValue,
  type DeviceStore,
  type IdentitySummary,
} from "@leonaid/features/offline";

import { prepareDevice } from "./device";

const USER = "10000000-0000-4000-8000-000000000007";
const DRIVEN = "20000000-0000-4000-8000-000000000001";
const ACQUIRED = "20000000-0000-4000-8000-000000000002";
const FETCHED = "2026-12-05T08:00:00.000Z";

/** The parts of DeviceStore the online start and the purge touch. */
class MemoryDevice {
  readonly userId = USER;
  readonly open = true;
  readonly cache = new Map<string, { value: unknown; fetchedAt: string }>();
  readonly meta = new Map<string, unknown>();

  async listCache(): Promise<CacheEntryInfo[]> {
    return [...this.cache.entries()].map(([id, { fetchedAt }]) => {
      const [kind, actionId] = id.split(":") as [CacheKind, string];
      return { actionId, fetchedAt, kind };
    });
  }
  async getCache<T>(
    kind: CacheKind,
    actionId: string,
  ): Promise<CachedValue<T> | undefined> {
    const record = this.cache.get(`${kind}:${actionId}`);
    return record
      ? {
          fetchedAt: record.fetchedAt,
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
    this.cache.set(`${kind}:${actionId}`, {
      fetchedAt,
      value: structuredClone(value),
    });
  }
  async deleteCache(kind: CacheKind, actionId: string) {
    this.cache.delete(`${kind}:${actionId}`);
  }
  async putMeta(name: string, value: unknown) {
    this.meta.set(name, value);
  }
  async deleteMeta(name: string) {
    this.meta.delete(name);
  }
  async queueCount() {
    return 0;
  }
  close() {}
}

/** A tour copy whose window is still open: only a flag removes it. */
function tourCopy(actionId: string) {
  return {
    fetchedAt: FETCHED,
    reads: [],
    tour: {
      actionId,
      actionName: "Krapfentaxi",
      days: [],
      map: { attribution: "", tileUrl: "" },
      startPoint: null,
      timezone: "Europe/Berlin",
      tour: {
        day: "2099-12-05",
        driverName: "",
        driverOrderedAt: null,
        driverUserId: USER,
        revision: "r1",
        windows: [
          {
            closed: false,
            endsAt: "2099-12-05T10:00:00Z",
            startsAt: "2099-12-05T08:00:00Z",
            stops: [],
            windowId: "70000000-0000-4000-8000-000000000001",
          },
        ],
      },
    },
  };
}

function seeded() {
  const device = new MemoryDevice();
  void device.putCache("tour", DRIVEN, tourCopy(DRIVEN), FETCHED);
  void device.putCache("tour", ACQUIRED, tourCopy(ACQUIRED), FETCHED);
  void device.putCache("board", ACQUIRED, { workItems: [] }, FETCHED);
  return device;
}

function evaluations(flags: Record<string, boolean>) {
  return {
    flags: Object.entries(flags).map(([key, enabled]) => ({ enabled, key })),
    surface: "pwa",
  } as unknown as FeatureFlagEvaluationListResponse;
}

const identity = {
  actionMemberships: [
    { actionId: DRIVEN, actionName: "Krapfentaxi", role: "driver" },
    { actionId: ACQUIRED, actionName: "Krapfentaxi B", role: "acquirer" },
  ],
  displayName: "Fahrer Franz",
  globalRoles: [],
  installation: { clubName: "Lions" },
  landingPath: "/app/",
  navigation: [],
  roleLabels: [],
  sessionExpiresAt: "2099-01-01T00:00:00Z",
  userId: USER,
} as unknown as CurrentIdentityResponse;

beforeEach(() => {
  // deviceStorageAvailable(): the store itself is the stand-in.
  vi.stubGlobal("indexedDB", { databases: async () => [] });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("online start (prepareDevice)", () => {
  async function start(flags: Record<string, boolean>) {
    const device = seeded();
    const client = {
      getFeatureFlagEvaluations: async () => evaluations(flags),
    } as unknown as LeonAidApiClient;
    const prepared = await prepareDevice(
      client,
      identity,
      device as unknown as DeviceStore,
    );
    return { device, prepared };
  }

  it("with delivery.tours off deletes every tour copy, keeps the board", async () => {
    const { device, prepared } = await start({
      [FEATURE_FLAGS.deliveryTours]: false,
      [FEATURE_FLAGS.pwaOfflineQueue]: true,
    });
    expect(prepared?.mode).toBe("on");
    expect([...device.cache.keys()]).toEqual([`board:${ACQUIRED}`]);
    const summary = device.meta.get(IDENTITY_META) as IdentitySummary;
    expect(summary.memberships.map((item) => item.role)).toEqual(["acquirer"]);
  });

  it("with both flags on keeps the tour of the driven action only", async () => {
    const { device } = await start({
      [FEATURE_FLAGS.deliveryTours]: true,
      [FEATURE_FLAGS.pwaOfflineQueue]: true,
    });
    expect([...device.cache.keys()].sort()).toEqual(
      [`board:${ACQUIRED}`, `tour:${DRIVEN}`].sort(),
    );
    const summary = device.meta.get(IDENTITY_META) as IdentitySummary;
    expect(summary.memberships.map((item) => item.role).sort()).toEqual([
      "acquirer",
      "driver",
    ]);
    expect(device.meta.get("flags")).toEqual({
      [FEATURE_FLAGS.deliveryTours]: true,
      [FEATURE_FLAGS.pwaOfflineQueue]: true,
    });
  });
});

describe("mid-session (useTourCachePurge)", () => {
  function mount(
    device: MemoryDevice,
    answer: () => Promise<FeatureFlagEvaluationListResponse>,
    cached?: ReadonlyMap<string, boolean>,
  ) {
    const client = {
      getFeatureFlagEvaluations: answer,
    } as unknown as LeonAidApiClient;
    function Purge() {
      useTourCachePurge();
      return null;
    }
    render(
      createElement(
        QueryClientProvider,
        {
          client: new QueryClient({
            defaultOptions: { queries: { retry: false } },
          }),
        },
        createElement(FeatureFlagProvider, {
          cached,
          children: createElement(
            OfflineRuntimeContext.Provider,
            {
              value: {
                enabled: true,
                queue: null,
                store: device as unknown as DeviceStore,
              },
            },
            createElement(Purge),
          ),
          client,
          identity,
          surface: "pwa",
        }),
      ),
    );
  }

  it.each([
    [FEATURE_FLAGS.deliveryTours, FEATURE_FLAGS.pwaOfflineQueue],
    [FEATURE_FLAGS.pwaOfflineQueue, FEATURE_FLAGS.deliveryTours],
  ])("Core answering %s off deletes the tour copies", async (off, on) => {
    const device = seeded();
    mount(device, async () => evaluations({ [off]: false, [on]: true }));
    await waitFor(() =>
      expect([...device.cache.keys()]).toEqual([`board:${ACQUIRED}`]),
    );
  });

  it("flags only assumed offline delete nothing", async () => {
    const device = seeded();
    let asked = 0;
    mount(
      device,
      async () => {
        asked += 1;
        throw new TypeError("Failed to fetch");
      },
      new Map([[FEATURE_FLAGS.deliveryTours, false]]),
    );
    await waitFor(() => expect(asked).toBe(1));
    await new Promise((done) => setTimeout(done, 20));
    expect(device.cache.size).toBe(3);
  });
});
