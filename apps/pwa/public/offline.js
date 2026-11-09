// Kept out of offline.html: the Content-Security-Policy forbids inline
// event handlers and inline scripts.
document
  .querySelector("[data-offline-retry]")
  ?.addEventListener("click", () => window.location.reload());

// With the offline queue on (specs/pwa-offline-queue §12.1), the service
// worker sends here only for areas that need a connection; the page says
// where offline work goes on: an acquirer's sponsors, a driver's tour
// (krapfentaxi-touren §9), or both. The PWA writes both settings.
const AUDIENCES = ["acquirer", "driver", "both"];
const main = document.querySelector("[data-offline-start]");
if (main && "caches" in window) {
  void caches
    .open("leonaid-pwa-settings")
    .then(async (cache) => {
      const enabled = await cache.match(
        main.getAttribute("data-offline-start"),
      );
      if (!enabled) return;
      const stored = await cache.match(
        main.getAttribute("data-offline-audience"),
      );
      const value = stored ? (await stored.text()).trim() : "";
      const audience = AUDIENCES.includes(value) ? value : "acquirer";
      for (const copy of document.querySelectorAll("[data-offline-copy]")) {
        copy.hidden =
          copy.getAttribute("data-offline-copy") !== "on" ||
          copy.getAttribute("data-audience") !== audience;
      }
    })
    .catch(() => undefined);
}
