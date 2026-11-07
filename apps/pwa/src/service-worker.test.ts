/*
 * The service worker's routing, run in a VM with an in-memory Cache
 * Storage: no `/api/` response is ever cached or answered (offline queue
 * §14.3), and `/app/` starts from the cached shell only while the page has
 * switched the offline start on (§8.1).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";
import { beforeEach, describe, expect, it } from "vitest";

const ORIGIN = "https://leonaid.test";
const BASE = "/app/";

class MemoryCache {
  readonly entries = new Map<string, Response>();

  async match(request: Request | string) {
    const key = new URL(
      typeof request === "string" ? request : request.url,
      ORIGIN,
    ).pathname;
    return this.entries.get(key)?.clone();
  }

  async put(request: Request | string, response: Response) {
    const key = new URL(
      typeof request === "string" ? request : request.url,
      ORIGIN,
    ).pathname;
    this.entries.set(key, response);
  }

  async delete(request: Request | string) {
    const key = new URL(
      typeof request === "string" ? request : request.url,
      ORIGIN,
    ).pathname;
    return this.entries.delete(key);
  }

  async addAll(urls: string[]) {
    for (const url of urls) {
      await this.put(url, new Response(`cached ${url}`, { status: 200 }));
    }
  }
}

class MemoryCacheStorage {
  readonly caches = new Map<string, MemoryCache>();

  async open(name: string) {
    let cache = this.caches.get(name);
    if (!cache) {
      cache = new MemoryCache();
      this.caches.set(name, cache);
    }
    return cache;
  }

  async keys() {
    return [...this.caches.keys()];
  }

  async delete(name: string) {
    return this.caches.delete(name);
  }
}

interface WorkerEvent {
  readonly request?: Request;
  readonly data?: unknown;
  respondWith?: (response: Promise<Response> | Response) => void;
  waitUntil: (promise: Promise<unknown>) => void;
}

function loadWorker(network: (request: Request) => Promise<Response>) {
  const listeners = new Map<string, (event: WorkerEvent) => void>();
  const storage = new MemoryCacheStorage();
  const state = { onLine: true };
  const source = readFileSync(
    resolve(__dirname, "../public/sw.js"),
    "utf8",
  ).replaceAll("__LEONAID_PWA_BASE__", BASE);
  const self = {
    addEventListener: (type: string, listener: (event: WorkerEvent) => void) =>
      listeners.set(type, listener),
    clients: { claim: async () => undefined },
    location: new URL(`${ORIGIN}${BASE}sw.js`),
    navigator: state,
    skipWaiting: () => undefined,
  };
  runInNewContext(source, {
    caches: storage,
    fetch: (request: Request) => network(request),
    Response,
    self,
    URL,
  });

  async function dispatch(type: string, event: Partial<WorkerEvent>) {
    const pending: Promise<unknown>[] = [];
    let response: Promise<Response> | Response | undefined;
    listeners.get(type)?.({
      ...event,
      respondWith: (value) => {
        response = value;
      },
      waitUntil: (promise) => pending.push(promise),
    });
    await Promise.all(pending);
    return response === undefined ? undefined : await response;
  }

  function navigate(path: string) {
    const request = new Request(`${ORIGIN}${path}`);
    Object.defineProperty(request, "mode", { value: "navigate" });
    return dispatch("fetch", { request });
  }

  return { dispatch, navigate, state, storage };
}

describe("service worker", () => {
  let requests: string[];
  let worker: ReturnType<typeof loadWorker>;

  beforeEach(async () => {
    requests = [];
    worker = loadWorker(async (request) => {
      requests.push(new URL(request.url).pathname);
      throw new TypeError("offline");
    });
    await worker.dispatch("install", {});
  });

  it("never answers or caches an API request", async () => {
    worker.state.onLine = false;
    const answer = await worker.dispatch("fetch", {
      request: new Request(`${ORIGIN}/api/v1/me`),
    });
    expect(answer).toBeUndefined();
    const navigation = await worker.navigate("/api/v1/me");
    expect(navigation).toBeUndefined();
    for (const cache of worker.storage.caches.values()) {
      expect(
        [...cache.entries.keys()].filter((key) => key.startsWith("/api/")),
      ).toEqual([]);
    }
  });

  it("explains the offline state while the offline start is off", async () => {
    worker.state.onLine = false;
    const answer = await worker.navigate(`${BASE}sponsors`);
    expect(await answer?.text()).toBe(`cached ${BASE}offline.html`);
  });

  it("starts the app shell offline once the page switched it on", async () => {
    worker.state.onLine = false;
    await worker.dispatch("message", {
      data: { type: "OFFLINE_START", enabled: true },
    });
    for (const path of [
      BASE,
      `${BASE}sponsors`,
      `${BASE}activities/`,
      `${BASE}commitments`,
      `${BASE}commitments/new`,
    ]) {
      const answer = await worker.navigate(path);
      expect(await answer?.text()).toBe(`cached ${BASE}`);
    }
    // Modules, the delivery board and unknown paths stay online-only.
    for (const path of [`${BASE}delivery`, `${BASE}tasks`, `${BASE}x/y`]) {
      const answer = await worker.navigate(path);
      expect(await answer?.text()).toBe(`cached ${BASE}offline.html`);
    }
    // Sign-out or the flag switched off: back to the explanation.
    await worker.dispatch("message", {
      data: { type: "OFFLINE_START", enabled: false },
    });
    const answer = await worker.navigate(`${BASE}sponsors`);
    expect(await answer?.text()).toBe(`cached ${BASE}offline.html`);
  });

  it("keeps the offline start setting across a new build's activation", async () => {
    await worker.dispatch("message", {
      data: { type: "OFFLINE_START", enabled: true },
    });
    await worker.storage.open("leonaid-pwa-oldbuild");
    await worker.dispatch("activate", {});
    expect(await worker.storage.keys()).toContain("leonaid-pwa-settings");
    expect(await worker.storage.keys()).not.toContain("leonaid-pwa-oldbuild");
  });

  it("tries the network first while online", async () => {
    await worker.dispatch("message", {
      data: { type: "OFFLINE_START", enabled: true },
    });
    const answer = await worker.navigate(`${BASE}sponsors`);
    expect(requests).toEqual([`${BASE}sponsors`]);
    // The network failed: the shell answers instead.
    expect(await answer?.text()).toBe(`cached ${BASE}`);
  });
});
