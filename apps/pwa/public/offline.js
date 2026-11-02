// Kept out of offline.html: the Content-Security-Policy forbids inline
// event handlers and inline scripts.
document
  .querySelector("[data-offline-retry]")
  ?.addEventListener("click", () => window.location.reload());
