// @vitest-environment jsdom
/*
 * The offline start setting for a service worker that is still installing
 * (#139 L1): once active it gets the setting as the pages last wrote it,
 * so another tab's sign-out is not overtaken by an older "true". Service
 * worker and Cache Storage are stubs here; the browser specs run them.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  CurrentIdentityResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import {
  ACTIVE_USER_KEY,
  forgetDevice,
  setOfflineAudience,
  setOfflineStart,
} from "@leonaid/features/offline";

import { prepareDevice } from "./device";

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

function stubCaches() {
  const entries = new Map<string, Response>();
  const cache = {
    delete: async (key: string) => entries.delete(key),
    match: async (key: string) => entries.get(key),
    put: async (key: string, value: Response) => {
      entries.set(key, value);
    },
  };
  vi.stubGlobal("caches", { open: async () => cache });
  return entries;
}

function stubInstallingWorker() {
  const listeners = new Set<() => void>();
  const messages: unknown[] = [];
  const worker = {
    addEventListener: (_type: string, listener: () => void) =>
      listeners.add(listener),
    postMessage: (message: unknown) => messages.push(message),
    removeEventListener: (_type: string, listener: () => void) =>
      listeners.delete(listener),
    state: "installing",
  };
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: {
      getRegistration: async () => ({
        active: null,
        installing: worker,
        waiting: null,
      }),
    },
  });
  const activate = async () => {
    worker.state = "activated";
    for (const listener of [...listeners]) listener();
    // The posts wait for the stored setting.
    await new Promise((resolve) => setTimeout(resolve, 0));
  };
  return { activate, listeners, messages };
}

describe("offline start for an installing worker (§8.1)", () => {
  it("reaches the worker once it is active", async () => {
    stubCaches();
    const worker = stubInstallingWorker();
    await setOfflineStart(true);
    expect(worker.messages).toEqual([]);
    await worker.activate();
    expect(worker.messages).toEqual([{ enabled: true, type: "OFFLINE_START" }]);
    // The listener is done once the worker is active.
    expect(worker.listeners.size).toBe(0);
  });

  it("sends the current setting, not an older one another tab replaced", async () => {
    const entries = stubCaches();
    const worker = stubInstallingWorker();
    // This tab switched it on while the worker installed ...
    await setOfflineStart(true);
    // ... then another tab signed out: it removed the setting itself.
    entries.clear();
    await worker.activate();
    expect(worker.messages).toEqual([
      { enabled: false, type: "OFFLINE_START" },
    ]);
  });
});

const USER_ID = "30000000-0000-4000-8000-000000000001";

/** IndexedDB as far as a deletion needs it. */
function stubIndexedDb() {
  const deleted: string[] = [];
  vi.stubGlobal("indexedDB", {
    deleteDatabase: (name: string) => {
      deleted.push(name);
      const request: { onsuccess?: () => void } = {};
      setTimeout(() => request.onsuccess?.(), 0);
      return request;
    },
  });
  return deleted;
}

describe("offline start with the flag off (§8.5)", () => {
  const client = {
    getFeatureFlagEvaluations: async () => ({ flags: [] }),
  } as unknown as LeonAidApiClient;
  const identity = {
    actionMemberships: [
      {
        actionId: "20000000-0000-4000-8000-000000000001",
        actionName: "Krapfentaxi 2026",
        role: "acquirer",
      },
    ],
    userId: USER_ID,
  } as unknown as CurrentIdentityResponse;

  it("leaves Cache Storage alone on a device that kept nothing", async () => {
    // Every online start forgets; a Cache API call cut off by the next
    // navigation is a page error in WebKit ("Context is stopped").
    const open = vi.fn();
    vi.stubGlobal("caches", { open });
    const deleted = stubIndexedDb();
    await expect(prepareDevice(client, identity)).resolves.toBeNull();
    expect(open).not.toHaveBeenCalled();
    expect(deleted).toEqual([`leonaid-pwa-v1-${USER_ID}`]);
  });

  it("switches the offline start off while a device user is recorded", async () => {
    const entries = stubCaches();
    stubIndexedDb();
    window.localStorage.setItem(ACTIVE_USER_KEY, USER_ID);
    await setOfflineAudience("driver");
    await setOfflineStart(true);
    expect(entries.size).toBe(2);
    await forgetDevice(USER_ID);
    // The offline page's audience goes with the offline start.
    expect([...entries.keys()]).toEqual([]);
    expect(window.localStorage.getItem(ACTIVE_USER_KEY)).toBeNull();
  });
});
