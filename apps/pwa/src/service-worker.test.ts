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

interface ShownNotification {
  readonly title: string;
  readonly options: {
    readonly body: string;
    readonly data: { readonly path: string };
    readonly icon: string;
    readonly tag: string;
  };
}

/** An open window of the app, as the worker's Clients API lists it. */
interface WindowStub {
  readonly url: string;
  readonly messages: unknown[];
  focused: boolean;
  /** A focus without a real click is refused by the browser. */
  readonly refuseFocus?: boolean;
}

interface WorkerEvent {
  readonly request?: Request;
  readonly data?: unknown;
  readonly notification?: {
    readonly data?: unknown;
    readonly close: () => void;
  };
  readonly ports?: readonly { postMessage: (message: unknown) => void }[];
  respondWith?: (response: Promise<Response> | Response) => void;
  waitUntil: (promise: Promise<unknown>) => void;
}

function loadWorker(network: (request: Request) => Promise<Response>) {
  const listeners = new Map<string, (event: WorkerEvent) => void>();
  const storage = new MemoryCacheStorage();
  const state = { onLine: true };
  const notifications: ShownNotification[] = [];
  const windows: WindowStub[] = [];
  const opened: string[] = [];
  const source = readFileSync(
    resolve(__dirname, "../public/sw.js"),
    "utf8",
  ).replaceAll("__LEONAID_PWA_BASE__", BASE);
  const self = {
    addEventListener: (type: string, listener: (event: WorkerEvent) => void) =>
      listeners.set(type, listener),
    clients: {
      claim: async () => undefined,
      matchAll: async () =>
        windows.map((window) => ({
          focus: async () => {
            if (window.refuseFocus) throw new TypeError("no user activation");
            window.focused = true;
          },
          postMessage: (message: unknown) => window.messages.push(message),
          url: window.url,
        })),
      openWindow: async (url: string) => {
        opened.push(url);
      },
    },
    location: new URL(`${ORIGIN}${BASE}sw.js`),
    navigator: state,
    registration: {
      showNotification: async (
        title: string,
        options: ShownNotification["options"],
      ) => {
        notifications.push({ options, title });
      },
    },
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

  /** A push as the browser hands it over: its data, or none. */
  async function push(data: unknown) {
    const text = typeof data === "string" ? data : JSON.stringify(data);
    await dispatch("push", {
      data:
        data === undefined ? null : { json: () => JSON.parse(text) as unknown },
    });
    return notifications.at(-1);
  }

  async function click(path: unknown) {
    let closed = false;
    await dispatch("notificationclick", {
      notification: {
        close: () => {
          closed = true;
        },
        data: path === undefined ? undefined : { path },
      },
    });
    return closed;
  }

  return {
    click,
    dispatch,
    navigate,
    notifications,
    opened,
    push,
    state,
    storage,
    windows,
  };
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
      // Every route of an offline screen, by the app's own prefix rule.
      `${BASE}commitments/new?action=a&assignment=b`,
      `${BASE}sponsors?view=new`,
      `${BASE}sponsors/anything/below`,
      `${BASE}activities?view=contacts`,
      // The driver's tour from the device copy (krapfentaxi-touren §9).
      `${BASE}delivery?action=a`,
    ]) {
      const answer = await worker.navigate(path);
      expect(await answer?.text()).toBe(`cached ${BASE}`);
    }
    // Modules and unknown paths stay online-only.
    for (const path of [
      `${BASE}tasks`,
      `${BASE}deliveryx`,
      `${BASE}x/y`,
      `${BASE}sponsorsx`,
      `${BASE}commitmentsnew`,
    ]) {
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

  it("reports its own offline start setting to a page that asks", async () => {
    const answers: unknown[] = [];
    const port = { postMessage: (message: unknown) => answers.push(message) };
    await worker.dispatch("message", {
      data: { type: "OFFLINE_START_STATUS" },
      ports: [port],
    });
    await worker.dispatch("message", {
      data: { type: "OFFLINE_START", enabled: true },
    });
    await worker.dispatch("message", {
      data: { type: "OFFLINE_START_STATUS" },
      ports: [port],
    });
    expect(answers).toEqual([{ enabled: false }, { enabled: true }]);
  });

  it("covers every screen the PWA routes from the device copy", () => {
    // app.tsx routes these screens by path prefix (currentRoute), and
    // each works from the device copy; sw.js must list every one.
    const app = readFileSync(resolve(__dirname, "app.tsx"), "utf8");
    const worker = readFileSync(resolve(__dirname, "../public/sw.js"), "utf8");
    const listed = worker.match(/OFFLINE_SCREENS = \[([^\]]*)\]/)?.[1] ?? "";
    for (const screen of [
      "sponsors",
      "activities",
      "commitments",
      "delivery",
    ]) {
      expect(app).toContain(`pathname.startsWith(pwaHref("${screen}"))`);
      expect(listed).toContain(`"${screen}"`);
    }
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

describe("service worker push notifications", () => {
  let worker: ReturnType<typeof loadWorker>;

  beforeEach(() => {
    worker = loadWorker(async () => {
      throw new TypeError("offline");
    });
  });

  it("writes the text on the device from kind and count", async () => {
    const texts: [string, number, string][] = [
      ["follow_ups", 1, "1 Wiedervorlage ist fällig."],
      ["follow_ups", 3, "3 Wiedervorlagen sind fällig."],
      ["feed", 1, "Es gibt eine neue Bestellung unter „Neues“."],
      ["feed", 4, "Es gibt 4 neue Bestellungen unter „Neues“."],
      ["tasks", 1, "Dir wurde eine Aufgabe zugewiesen."],
      ["tasks", 2, "Dir wurden 2 Aufgaben zugewiesen."],
      ["delivery", 1, "Dir wurde eine Lieferung zugewiesen."],
      ["delivery", 12, "Dir wurden 12 Lieferungen zugewiesen."],
      ["test", 1, "Benachrichtigungen funktionieren auf diesem Gerät."],
    ];
    for (const [kind, count, body] of texts) {
      const shown = await worker.push({ count, kind, path: `${BASE}tasks` });
      expect(shown).toEqual({
        options: {
          badge: `${BASE}icons/icon-192.svg`,
          body,
          data: { path: `${BASE}tasks` },
          icon: `${BASE}icons/icon-192.svg`,
          lang: "de",
          renotify: true,
          // One notification per kind: the newer one replaces the older.
          tag: `leonaid-${kind}`,
        },
        title: "LeonAid",
      });
    }
    expect(worker.notifications).toHaveLength(texts.length);
  });

  it("shows a notification for every push, also one it cannot read", async () => {
    // A browser ends a subscription whose pushes show nothing.
    const unreadable = [
      undefined,
      "not json",
      { count: 1, kind: "orders", path: `${BASE}orders` },
      { count: 0, kind: "feed", path: `${BASE}activities` },
      { count: "3", kind: "feed", path: `${BASE}activities` },
      { kind: "feed", path: `${BASE}activities` },
      { count: 1, kind: "constructor", path: `${BASE}activities` },
      null,
    ];
    for (const data of unreadable) {
      const shown = await worker.push(data);
      expect(shown?.options.body).toBe("Es gibt Neues in LeonAid.");
      expect(shown?.options.data).toEqual({ path: BASE });
      expect(shown?.options.tag).toBe("leonaid-news");
    }
    expect(worker.notifications).toHaveLength(unreadable.length);
  });

  it("never leads out of the app", async () => {
    for (const path of [
      "https://attacker.example/",
      "//attacker.example/app/",
      "/admin/",
      "/apps",
      42,
      undefined,
    ]) {
      const shown = await worker.push({ count: 1, kind: "feed", path });
      expect(shown?.options.data).toEqual({ path: BASE });
      // A stored notification of an older worker is checked again.
      expect(await worker.click(path)).toBe(true);
      expect(worker.opened.at(-1)).toBe(BASE);
    }
  });

  it("opens the app at the target when no window is open", async () => {
    worker.windows.push({
      focused: false,
      messages: [],
      // Another page of the origin is not the app.
      url: `${ORIGIN}/admin/`,
    });
    expect(await worker.click(`${BASE}activities?view=contacts`)).toBe(true);
    expect(worker.opened).toEqual([`${BASE}activities?view=contacts`]);
    expect(worker.windows[0]?.messages).toEqual([]);
  });

  it("moves the open app to the target and brings it forward", async () => {
    const open: WindowStub = {
      focused: false,
      messages: [],
      url: `${ORIGIN}${BASE}sponsors`,
    };
    worker.windows.push(open);
    await worker.click(`${BASE}delivery`);
    expect(open.messages).toEqual([
      { path: `${BASE}delivery`, type: "PUSH_NAVIGATE" },
    ]);
    expect(open.focused).toBe(true);
    expect(worker.opened).toEqual([]);
  });

  it("still moves the app when the browser refuses the focus", async () => {
    const open: WindowStub = {
      focused: false,
      messages: [],
      refuseFocus: true,
      url: `${ORIGIN}${BASE}`,
    };
    worker.windows.push(open);
    await worker.click(`${BASE}tasks`);
    expect(open.messages).toEqual([
      { path: `${BASE}tasks`, type: "PUSH_NAVIGATE" },
    ]);
    expect(worker.opened).toEqual([]);
  });

  it("carries the paths Core sends for each kind", () => {
    // domain/push.py names the target of each kind; the worker only
    // accepts paths of the app, so both must agree on the base.
    const domain = readFileSync(
      resolve(__dirname, "../../../src/leonaid/domain/push.py"),
      "utf8",
    );
    for (const kind of ["follow_ups", "feed", "tasks", "delivery"]) {
      expect(domain).toContain(`${kind.toUpperCase()} = "${kind}"`);
    }
    expect(domain).toContain('TEST_KIND: Final = "test"');
    const source = readFileSync(resolve(__dirname, "../public/sw.js"), "utf8");
    for (const kind of ["follow_ups", "feed", "tasks", "delivery", "test"]) {
      expect(source).toMatch(new RegExp(`\\b${kind}: \\(`));
    }
  });
});
