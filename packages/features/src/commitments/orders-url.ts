/*
 * Older links into /admin/orders carry their own query parameters:
 * - `status=<status>|all` (dashboard tile, old status tabs),
 * - `commitment=<id>` (activity feed "next step"),
 * - `invoice=<id>` (invoice review, also the fresh sign-in return URL).
 * The list view reads `view`, `f.status` and `open` instead. This maps the
 * old parameters once, before the list mounts. `invoice` stays in the URL:
 * it keeps the review open across the fresh sign-in round trip.
 */

const statuses = new Set([
  "draft",
  "review_ready",
  "confirmed",
  "invoiced",
  "cancelled",
]);

/** The list view's query for an old orders URL, or null when nothing maps. */
export function legacyOrdersSearch(search: string): string | null {
  const params = new URLSearchParams(search);
  let changed = false;

  const status = params.get("status");
  if (status !== null) {
    params.delete("status");
    changed = true;
    const hasListState = params.has("view") || params.has("f.status");
    if (!hasListState && (status === "all" || statuses.has(status))) {
      params.set("view", "all");
      if (status !== "all") params.set("f.status", status);
    }
  }

  const commitment = params.get("commitment");
  if (commitment !== null) {
    params.delete("commitment");
    changed = true;
    if (commitment && !params.has("open")) params.set("open", commitment);
  }

  const invoice = params.get("invoice");
  if (invoice && params.get("open") !== invoice) {
    params.set("open", invoice);
    changed = true;
  }

  if (!changed) return null;
  const query = params.toString();
  return query ? `?${query}` : "";
}

/** Rewrites the current URL in place (no history entry). */
export function normalizeOrdersUrl() {
  const next = legacyOrdersSearch(window.location.search);
  if (next === null) return;
  window.history.replaceState(
    window.history.state,
    "",
    `${window.location.pathname}${next}${window.location.hash}`,
  );
}

/** Sets or removes `invoice=<id>` without a history entry. */
export function setInvoiceSelection(commitmentId?: string) {
  const url = new URL(window.location.href);
  if (commitmentId) url.searchParams.set("invoice", commitmentId);
  else url.searchParams.delete("invoice");
  window.history.replaceState(
    window.history.state,
    "",
    `${url.pathname}${url.search}${url.hash}`,
  );
}
