// The build replaces the placeholders (see vite.config.ts): the build ID, the
// asset list and __LEONAID_PWA_BASE__, the PWA base path of
// packages/ui/src/lib/base-paths.ts. A new build ID changes this file's
// bytes, so browsers install the update, the app shows its update banner and
// activation deletes the previous build's cache.
const BUILD_ID = "__LEONAID_BUILD_ID__";
const BUILD_ASSETS = /* __LEONAID_BUILD_ASSETS__ */ [];
const CACHE_NAME = `leonaid-pwa-${BUILD_ID}`;
// Outlives builds: whether /app/ may start from the cache. The page sets it
// while the flag pwa.offline_queue is on (specs/pwa-offline-queue §8.1).
const SETTINGS_CACHE = "leonaid-pwa-settings";
const OFFLINE_START_KEY = "__LEONAID_PWA_BASE__offline-start";
const SHELL_URL = "__LEONAID_PWA_BASE__";
const OFFLINE_URL = "__LEONAID_PWA_BASE__offline.html";
// App screens that work from the device copy; every other path (modules,
// the delivery board, unknown paths) keeps the offline explanation.
const OFFLINE_SCREENS = ["sponsors", "activities", "commitments"];
// The offline page loads its stylesheet and script from files because the
// Content-Security-Policy forbids inline code; they are cached with it.
const OFFLINE_RESOURCES = [
  "__LEONAID_PWA_BASE__offline.css",
  "__LEONAID_PWA_BASE__offline.js",
];
const APP_SHELL = [
  "__LEONAID_PWA_BASE__",
  OFFLINE_URL,
  ...OFFLINE_RESOURCES,
  "__LEONAID_PWA_BASE__theme-init.js",
  "__LEONAID_PWA_BASE__icons/icon.svg",
  "__LEONAID_PWA_BASE__icons/icon-192.svg",
  "__LEONAID_PWA_BASE__icons/icon-512.svg",
  "__LEONAID_PWA_BASE__manifest.webmanifest",
  ...BUILD_ASSETS,
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter(
              (key) =>
                key.startsWith("leonaid-pwa-") &&
                key !== CACHE_NAME &&
                key !== SETTINGS_CACHE,
            )
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
  if (event.data?.type === "OFFLINE_START") {
    event.waitUntil(setOfflineStart(event.data.enabled === true));
  }
});

async function setOfflineStart(enabled) {
  const settings = await caches.open(SETTINGS_CACHE);
  if (enabled) {
    await settings.put(
      OFFLINE_START_KEY,
      new Response("true", { headers: { "content-type": "text/plain" } }),
    );
  } else {
    await settings.delete(OFFLINE_START_KEY);
  }
}

async function offlineStartEnabled() {
  const settings = await caches.open(SETTINGS_CACHE);
  return Boolean(await settings.match(OFFLINE_START_KEY));
}

function isOfflineScreen(pathname) {
  if (!pathname.startsWith(SHELL_URL)) return false;
  // The screen is the first segment: /app/commitments/new is the order form.
  const screen = pathname.slice(SHELL_URL.length).split("/")[0];
  return screen === "" || OFFLINE_SCREENS.includes(screen);
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (
    url.origin !== self.location.origin ||
    !url.pathname.startsWith("__LEONAID_PWA_BASE__")
  ) {
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      (async () => {
        if (self.navigator.onLine !== false) {
          try {
            const response = await fetch(request);
            if (response.ok) return response;
          } catch {
            // The cached explanation below is the deliberate offline behavior.
          }
        }
        const cache = await caches.open(CACHE_NAME);
        if (isOfflineScreen(url.pathname) && (await offlineStartEnabled())) {
          const shell = await cache.match(SHELL_URL);
          if (shell) return shell;
        }
        return (await cache.match(OFFLINE_URL)) ?? Response.error();
      })(),
    );
    return;
  }

  if (OFFLINE_RESOURCES.includes(url.pathname)) {
    event.respondWith(
      caches
        .open(CACHE_NAME)
        .then(async (cache) => (await cache.match(request)) ?? fetch(request)),
    );
    return;
  }

  if (url.pathname.startsWith("__LEONAID_PWA_BASE__assets/")) {
    event.respondWith(
      caches.open(CACHE_NAME).then(async (cache) => {
        const cached = await cache.match(request);
        if (cached) return cached;
        const response = await fetch(request);
        // Never store an HTML fallback under a script or style URL.
        const contentType = response.headers.get("content-type") ?? "";
        if (response.ok && !contentType.includes("text/html")) {
          await cache.put(request, response.clone());
        }
        return response;
      }),
    );
  }
});
