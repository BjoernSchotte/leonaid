// Offline queue, lost acknowledgement (specs/pwa-offline-queue §15, G2):
// one real contact request reaches Core and is committed; only its first
// answer is dropped on the way back (connection reset). The queue resends
// the same capture with the same Idempotency-Key, Core replays it, and the
// contact exists once. Every other request and response passes unchanged
// from the real API.
import { expect, test } from "./csp-guard.mjs";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const annaSession = process.env.ANNA_SESSION;

if (!baseUrl || !annaSession) {
  throw new Error("LEONAID_E2E_BASE_URL und ANNA_SESSION sind erforderlich");
}

const ACTION_ID = "20000000-0000-4000-8000-000000000001";

test.use({
  ignoreHTTPSErrors: true,
  launchOptions:
    process.env.LEONAID_E2E_BROWSER === "chromium"
      ? { args: ["--ignore-certificate-errors"] }
      : {},
  // Requests of a page under a service worker bypass page.route; this
  // spec needs no offline start, so the worker stays out.
  serviceWorkers: "block",
  viewport: { width: 390, height: 844 },
});

test("a lost answer is resent with the same key and stored once", async ({
  browserName,
  context,
  page,
}) => {
  test.setTimeout(120_000);
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: annaSession,
      url: baseUrl,
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
    },
  ]);
  const keys = [];
  let dropped = false;
  await page.route(
    `**/api/v1/actions/${ACTION_ID}/acquisition/activities`,
    async (route) => {
      const request = route.request();
      if (request.method() !== "POST") return route.continue();
      keys.push(request.headers()["idempotency-key"]);
      if (dropped) return route.continue();
      // The real request reaches Core and commits; its answer is lost.
      const response = await route.fetch();
      dropped = response.status() === 201;
      return route.abort("connectionreset");
    },
  );

  await page.goto(`${baseUrl}/app/sponsors`);
  // The capture queue is ready (the glyph opens it).
  await expect(page.getByTestId("network-state")).toHaveAttribute(
    "data-queue-state",
    "empty",
  );
  await page
    .getByTestId("sponsor-row")
    .filter({ hasText: "Musterwerk GmbH" })
    .click();
  const note = `Antwort verloren ${browserName} ${Date.now()}`;
  await page.getByTestId("contact-open").click();
  await page
    .getByTestId("contact-sheet")
    .getByText("Erreicht", { exact: true })
    .click();
  await page.locator("#activity-note").fill(note);
  await page.getByTestId("activity-submit").click();

  // The backoff resend replays: the queue empties without a tap.
  await expect
    .poll(() => keys.length, { timeout: 30_000 })
    .toBeGreaterThanOrEqual(2);
  await expect(page.getByTestId("network-state")).toHaveAttribute(
    "data-queue-state",
    "empty",
    { timeout: 30_000 },
  );
  expect(dropped).toBe(true);
  expect(keys.length).toBeGreaterThanOrEqual(2);
  expect(new Set(keys).size).toBe(1);
  expect(keys[0]).toMatch(/^pwa-q:[0-9a-f-]{36}$/);

  const board = await (
    await page.request.get(
      `${baseUrl}/api/v1/actions/${ACTION_ID}/acquisition/activity-board?limit=100`,
    )
  ).json();
  expect(board.activities.filter((item) => item.note === note)).toHaveLength(1);
});
