// "Meine Tour" offline (specs/krapfentaxi-touren §9, §10; Ruling 22): a
// driver starts without network on the device copy of today's tour, marks
// a stop delivered and reorders; after reconnect both reach Core in order,
// the offline read reaches the audit with its own time, and with
// `delivery.tours` off no tour stays on the device. Real stack, no
// interception; tools/pwa/tour_setup.py prepares Dora's tour.
import { existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";

import { expect as baseExpect, test } from "./csp-guard.mjs";

const expect = baseExpect.configure({ timeout: 30_000 });

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const doraSession = process.env.DORA_SESSION;

if (!baseUrl || !artifactDirectory || !doraSession) {
  throw new Error(
    "LEONAID_E2E_BASE_URL, LEONAID_E2E_ARTIFACT_DIR und DORA_SESSION sind erforderlich",
  );
}

const ACTION_ID = "20000000-0000-4000-8000-000000000001";
const DORA_ID = "10000000-0000-4000-8000-0000000000d1";
const EINS = "80000000-0000-4000-8000-0000000000d1";
const ZWEI = "80000000-0000-4000-8000-0000000000d2";
const DREI = "80000000-0000-4000-8000-0000000000d3";

test.describe.configure({ timeout: 120_000 });

test.use({
  ignoreHTTPSErrors: true,
  launchOptions:
    process.env.LEONAID_E2E_BROWSER === "chromium"
      ? { args: ["--ignore-certificate-errors"] }
      : {},
  viewport: { width: 390, height: 844 },
});

/** Asks tools/pwa/test.sh for a database change and waits until it is done. */
async function serverChange(name) {
  const done = `${artifactDirectory}/offline-done-${name}`;
  const failed = `${artifactDirectory}/offline-failed-${name}`;
  rmSync(done, { force: true });
  rmSync(failed, { force: true });
  writeFileSync(`${artifactDirectory}/offline-request-${name}`, "");
  await expect
    .poll(
      () => (existsSync(failed) ? "failed" : existsSync(done) ? "done" : ""),
      { timeout: 60_000 },
    )
    .toBe("done");
}

/** The kinds of Dora's device cache records; null without her database. */
function cacheKinds(page) {
  return page.evaluate(async (userId) => {
    const name = `leonaid-pwa-v1-${userId}`;
    if (!(await indexedDB.databases()).some((item) => item.name === name)) {
      return null;
    }
    const database = await new Promise((resolve, reject) => {
      const request = indexedDB.open(name);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    try {
      if (!database.objectStoreNames.contains("cache")) return [];
      const keys = await new Promise((resolve, reject) => {
        const request = database
          .transaction("cache")
          .objectStore("cache")
          .getAllKeys();
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      return keys.map((key) => String(key).split(":")[0]).sort();
    } finally {
      database.close();
    }
  }, DORA_ID);
}

/** The service worker controls the page and may start `/app/` offline. */
async function offlineReady(page) {
  await expect
    .poll(() =>
      page.evaluate(async () =>
        Boolean((await navigator.serviceWorker.getRegistration())?.active),
      ),
    )
    .toBe(true);
  await page.reload();
  await expect
    .poll(() =>
      page.evaluate(() => Boolean(navigator.serviceWorker.controller)),
    )
    .toBe(true);
  await expect.poll(() => cacheKinds(page)).toContain("tour");
  await expect
    .poll(() =>
      page.evaluate(async () => {
        const worker = (await navigator.serviceWorker.getRegistration())
          ?.active;
        if (!worker) return false;
        return new Promise((resolve) => {
          const channel = new MessageChannel();
          channel.port1.onmessage = (event) =>
            resolve(event.data?.enabled === true);
          worker.postMessage({ type: "OFFLINE_START_STATUS" }, [channel.port2]);
          setTimeout(() => resolve(false), 2_000);
        });
      }),
    )
    .toBe(true);
}

const openNames = (page) =>
  page.getByTestId("tour-stop").getByTestId("tour-stop-name").allInnerTexts();

test("a driver delivers and reorders offline; reconnect replays both and keeps the read", async ({
  browserName,
  context,
  page,
}) => {
  // One browser carries the journey (CI leg budget); WebKit keeps the
  // device-store proofs of pwa-offline.spec.mjs.
  test.skip(browserName !== "chromium", "offline tour journey in Chromium");
  await serverChange("tour-setup");
  try {
    await context.addCookies([
      {
        name: "__Host-leonaid_session",
        value: doraSession,
        url: baseUrl,
        httpOnly: true,
        secure: true,
        sameSite: "Lax",
      },
    ]);
    // Online once: someone who only drives lands on the tour, and the
    // device keeps it.
    await page.goto(`${baseUrl}/app/`);
    const dockName = page.getByTestId("tour-next-stop").locator("h2");
    await expect(dockName).toHaveText("Tour Eins KG");
    await offlineReady(page);
    // Only the offline view below may count as today's read.
    await serverChange("tour-reads-reset");

    // 1. Offline start: "Meine Tour" from the device, with its time.
    await context.setOffline(true);
    const readFrom = Date.now();
    await page.goto(`${baseUrl}/app/`);
    await expect(page.getByTestId("tour-offline")).toContainText(
      /Offline – Stand \d\d:\d\d/,
    );
    const readUntil = Date.now();
    await expect(page.getByTestId("offline-banner")).toContainText(
      "Zustellungen und deine Reihenfolge speichert LeonAid auf diesem Gerät",
    );
    await expect(dockName).toHaveText("Tour Eins KG");

    // 2. Zugestellt and a move, both queued and shown at once.
    await page
      .getByTestId("tour-next-stop")
      .getByRole("button", { name: "Zugestellt" })
      .click();
    await expect(
      page.getByText(
        "Tour Eins KG: zugestellt. Wird gesendet, sobald du online bist.",
      ),
    ).toBeVisible();
    await expect(dockName).toHaveText("Tour Zwei KG");
    expect(await openNames(page)).toEqual(["Tour Zwei KG", "Tour Drei KG"]);
    await page
      .getByRole("button", { name: "Stopp verschieben: Tour Zwei KG" })
      .focus();
    for (const key of ["Space", "ArrowDown", "Space"]) {
      await page.keyboard.press(key);
      await page.waitForTimeout(100);
    }
    await expect
      .poll(() => openNames(page))
      .toEqual(["Tour Drei KG", "Tour Zwei KG"]);
    await expect(
      page.getByText(
        "Reihenfolge gemerkt. Sie wird gesendet, sobald du online bist.",
      ),
    ).toBeVisible();
    await expect(page.getByText("Reihenfolge gespeichert.")).toHaveCount(0);
    const indicator = page.getByTestId("network-state");
    await expect(indicator).toHaveAccessibleName(
      "2 Einträge warten auf Versand",
    );
    // A reload without network (the start moved to /app/delivery) keeps
    // both, on top of the device copy.
    expect(new URL(page.url()).pathname).toBe("/app/delivery");
    await page.reload();
    await expect(dockName).toHaveText("Tour Drei KG");
    expect(await openNames(page)).toEqual(["Tour Drei KG", "Tour Zwei KG"]);
    await indicator.click();
    const sheet = page.getByTestId("queue-sheet");
    await expect(sheet.getByTestId("queue-entry")).toHaveCount(2);
    await expect(sheet).toContainText("Zustellung Tour Eins KG: zugestellt");
    await expect(sheet).toContainText("Tour-Reihenfolge");
    await page.screenshot({
      path: `${artifactDirectory}/pwa-offline-tour-${browserName}.png`,
    });
    await page.keyboard.press("Escape");
    // An online-only area: the offline page points a driver to the tour,
    // not to sponsors (Ruling 22).
    await page.goto(`${baseUrl}/app/tasks`);
    await expect(page).toHaveTitle("LeonAid ist offline");
    const copy = page.locator("[data-offline-copy]:visible");
    await expect(copy).toContainText("Zu meiner Tour");
    await expect(copy).not.toContainText("Sponsoren");
    await page.goto(`${baseUrl}/app/delivery`);
    await expect(dockName).toHaveText("Tour Drei KG");

    // 3. Reconnect: the reads, then the entries in the order they were made.
    const writes = [];
    page.on("request", (request) => {
      if (request.method() === "PUT" && request.url().includes("/api/v1/")) {
        writes.push(new URL(request.url()).pathname);
      }
    });
    const reads = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url().endsWith(`/actions/${ACTION_ID}/my-tour/reads`),
    );
    await context.setOffline(false);
    expect((await reads).status()).toBe(204);
    await expect(indicator).toHaveAttribute("data-queue-state", "empty");
    expect(writes).toEqual([
      `/api/v1/actions/${ACTION_ID}/commitments/${EINS}/delivery-state`,
      `/api/v1/actions/${ACTION_ID}/my-tour/order`,
    ]);
    await expect(page.getByTestId("tour-offline")).toHaveCount(0);
    expect(await openNames(page)).toEqual(["Tour Drei KG", "Tour Zwei KG"]);

    // Core has both.
    const served = await page.request.get(
      `${baseUrl}/api/v1/actions/${ACTION_ID}/my-tour`,
    );
    expect(served.ok()).toBe(true);
    const stops = (await served.json()).tour.windows
      .flatMap((window) => window.stops)
      .toSorted((a, b) => a.effectiveRank - b.effectiveRank);
    expect(stops.map((stop) => stop.drop.commitmentId)).toEqual([
      EINS,
      DREI,
      ZWEI,
    ]);
    expect(stops.map((stop) => stop.drop.state)).toEqual([
      "delivered",
      "open",
      "open",
    ]);
    expect(stops.every((stop) => stop.driverRank !== null)).toBe(true);

    // The audit keeps the offline read's time, not the later online load.
    await serverChange("tour-audit");
    const kept = readFileSync(
      `${artifactDirectory}/offline-result-tour-audit`,
      "utf8",
    ).trim();
    expect(kept).not.toBe("");
    const keptAt = Date.parse(kept);
    expect(keptAt).toBeGreaterThanOrEqual(readFrom - 1_000);
    expect(keptAt).toBeLessThanOrEqual(readUntil + 1_000);

    // 4. delivery.tours off: after a reload no tour stays on the device.
    await serverChange("tours-off");
    await page.reload();
    await expect
      .poll(async () => (await cacheKinds(page))?.includes("tour") ?? false)
      .toBe(false);
  } finally {
    await serverChange("tour-teardown");
  }
});
