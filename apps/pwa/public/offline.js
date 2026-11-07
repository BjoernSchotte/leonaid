// Kept out of offline.html: the Content-Security-Policy forbids inline
// event handlers and inline scripts.
document
  .querySelector("[data-offline-retry]")
  ?.addEventListener("click", () => window.location.reload());

// With the offline queue on (specs/pwa-offline-queue §12.1), the service
// worker sends here only for areas that need a connection; the page says
// where offline capture works. The setting is the service worker's own.
const main = document.querySelector("[data-offline-start]");
if (main && "caches" in window) {
  void caches
    .open("leonaid-pwa-settings")
    .then((cache) => cache.match(main.getAttribute("data-offline-start")))
    .then((enabled) => {
      if (!enabled) return;
      for (const copy of document.querySelectorAll("[data-offline-copy]")) {
        copy.hidden = copy.getAttribute("data-offline-copy") !== "on";
      }
    })
    .catch(() => undefined);
}
