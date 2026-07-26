const CACHE_NAME = "leonaid-pwa-v3";
const OFFLINE_URL = "/app/offline.html";
const APP_SHELL = [
  "/app/",
  OFFLINE_URL,
  "/app/icons/icon.svg",
  "/app/icons/icon-192.svg",
  "/app/icons/icon-512.svg",
  "/app/manifest.webmanifest",
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
              (key) => key.startsWith("leonaid-pwa-") && key !== CACHE_NAME,
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
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (
    url.origin !== self.location.origin ||
    !url.pathname.startsWith("/app/")
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
        return (await cache.match(OFFLINE_URL)) ?? Response.error();
      })(),
    );
    return;
  }

  if (url.pathname.startsWith("/app/assets/")) {
    event.respondWith(
      caches.open(CACHE_NAME).then(async (cache) => {
        const cached = await cache.match(request);
        if (cached) return cached;
        const response = await fetch(request);
        if (response.ok) await cache.put(request, response.clone());
        return response;
      }),
    );
  }
});
