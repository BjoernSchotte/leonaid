// Offline queue stage 1 (specs/pwa-offline-queue §8, §16): with the flag
// pwa.offline_queue on, the PWA starts without network from the cached
// shell, shows the acquirer's own sponsors and the order context from the
// encrypted device copy, and clears the device on account switch and
// sign-out. Runs against the real stack (tools/pwa/test.sh switches the
// flag on before and off after this spec); no request is intercepted.
import { analyzeAccessibility } from "./axe.mjs";
import { expect as baseExpect, test } from "./csp-guard.mjs";

const expect = baseExpect.configure({ timeout: 60_000 });

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const annaSession = process.env.ANNA_SESSION;

if (!baseUrl || !artifactDirectory || !annaSession) {
  throw new Error(
    "LEONAID_E2E_BASE_URL, LEONAID_E2E_ARTIFACT_DIR und ANNA_SESSION sind erforderlich",
  );
}

const ANNA_ID = "10000000-0000-4000-8000-000000000004";
// The second acquirer signs out at the end, which ends that session; each
// browser run takes its own persona (sessions from tools/pwa/contract.py).
const SECOND_ACQUIRER = {
  chromium: { id: "10000000-0000-4000-8000-000000000005", name: /Bernd/ },
  webkit: { id: "10000000-0000-4000-8000-000000000006", name: /Carla/ },
};

function sessionFor(userId) {
  return `poc062-${userId}-server-session-token-value`;
}

// The board reads the CRM, which Core limits to 100 requests a minute for
// the whole installation; after the heavier specs a first load can wait.
test.describe.configure({ timeout: 240_000 });

test.use({
  ignoreHTTPSErrors: true,
  // Chromium registers a service worker over the test CA only with this
  // switch (as in pwa-audit.spec.mjs); WebKit follows ignoreHTTPSErrors.
  launchOptions:
    process.env.LEONAID_E2E_BROWSER === "chromium"
      ? { args: ["--ignore-certificate-errors"] }
      : {},
  viewport: { width: 390, height: 844 },
});

async function authenticate(context, token) {
  await context.clearCookies();
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: token,
      url: baseUrl,
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
    },
  ]);
}

/**
 * Waits until the service worker is active and controls the page: the
 * first load registers it, a reload puts the page under it.
 */
async function controlled(page) {
  await expect
    .poll(
      async () => {
        try {
          return await page.evaluate(async () =>
            Boolean((await navigator.serviceWorker.getRegistration())?.active),
          );
        } catch {
          return false;
        }
      },
      { timeout: 30_000 },
    )
    .toBe(true);
  await page.reload();
  await expect
    .poll(() =>
      page.evaluate(() => Boolean(navigator.serviceWorker.controller)),
    )
    .toBe(true);
}

/**
 * The service worker itself reports that `/app/` may start offline (§8.1):
 * the setting reaches it after the current page load prepared the device,
 * which a copy left by an earlier load does not show.
 */
async function offlineStartReady(page) {
  await expect
    .poll(
      () =>
        page.evaluate(async () => {
          const registration = await navigator.serviceWorker.getRegistration();
          const worker = registration?.active;
          if (!worker) return false;
          return new Promise((resolve) => {
            const channel = new MessageChannel();
            channel.port1.onmessage = (event) =>
              resolve(event.data?.enabled === true);
            worker.postMessage({ type: "OFFLINE_START_STATUS" }, [
              channel.port2,
            ]);
            setTimeout(() => resolve(false), 2_000);
          });
        }),
      { timeout: 30_000 },
    )
    .toBe(true);
}

/** Raw IndexedDB view of one user's device database, as a copy would see it. */
function rawDatabase(page, userId) {
  return page.evaluate(async (id) => {
    const names = (await indexedDB.databases()).map((item) => item.name);
    const name = `leonaid-pwa-v1-${id}`;
    if (!names.includes(name)) return null;
    const database = await new Promise((resolve, reject) => {
      const request = indexedDB.open(name);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    const all = (store) =>
      new Promise((resolve, reject) => {
        const request = database.transaction(store).objectStore(store).getAll();
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
    const [cache, meta] = await Promise.all([all("cache"), all("meta")]);
    const keyRecord = meta.find((record) => record.name === "device-key");
    let exportable = true;
    try {
      await crypto.subtle.exportKey("raw", keyRecord.key);
    } catch {
      exportable = false;
    }
    const decoded = (records) =>
      records
        .map((record) =>
          record.sealed
            ? new TextDecoder("utf-8", { fatal: false }).decode(
                record.sealed.data,
              )
            : "",
        )
        .join("\n");
    database.close();
    return {
      cacheIds: cache.map((record) => record.id).sort(),
      clearText: decoded(cache) + decoded(meta),
      keyExtractable: keyRecord.key.extractable,
      keyExportable: exportable,
      metaNames: meta.map((record) => record.name).sort(),
    };
  }, userId);
}

function databaseNames(page) {
  return page.evaluate(async () =>
    (await indexedDB.databases())
      .map((item) => item.name)
      .filter((name) => name.startsWith("leonaid-pwa-v1-"))
      .sort(),
  );
}

test("the PWA starts offline from the encrypted device copy", async ({
  browserName,
  context,
  page,
}) => {
  await authenticate(context, annaSession);
  await page.goto(`${baseUrl}/app/sponsors`);
  await expect(
    page.getByTestId("sponsor-row").filter({ hasText: "Musterwerk GmbH" }),
  ).toBeVisible();
  await controlled(page);

  // The read cache: sponsor list and order context of Anna's campaign.
  await expect
    .poll(async () => (await rawDatabase(page, ANNA_ID))?.cacheIds ?? [], {
      timeout: 30_000,
    })
    .toEqual(
      expect.arrayContaining([
        expect.stringMatching(/^board:/),
        expect.stringMatching(/^capture:/),
      ]),
    );
  const raw = await rawDatabase(page, ANNA_ID);
  // §8.4: non-extractable key; no clear text in a copy of the database.
  expect(raw.keyExtractable).toBe(false);
  expect(raw.keyExportable).toBe(false);
  // "flags": the flag values of the last online start, for an offline
  // start (krapfentaxi-touren §9); no personal data.
  expect(raw.metaNames).toEqual([
    "device-key",
    "flags",
    "identity",
    "offlineEnabled",
  ]);
  for (const secret of [
    "Musterwerk",
    "mara.muster",
    "+493012345678",
    "Anna",
    "@leonaid.invalid",
  ]) {
    expect(raw.clearText).not.toContain(secret);
  }
  expect(
    await page.evaluate(() => localStorage.getItem("leonaid-pwa-active-user")),
  ).toBe(ANNA_ID);

  // §8.1: offline, /app/ starts from the cached shell.
  await offlineStartReady(page);
  await context.setOffline(true);
  await page.reload();
  await expect(page.getByTestId("offline-banner")).toBeVisible();
  await expect(page.getByTestId("display-name")).toHaveText(/Anna/);
  const row = page
    .getByTestId("sponsor-row")
    .filter({ hasText: "Musterwerk GmbH" });
  await expect(row).toBeVisible();
  // D2: call or write without data; no street address on the device.
  await row.click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Musterwerk GmbH" }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Anrufen" })).toHaveAttribute(
    "href",
    "tel:+493012345678",
  );
  await expect(page.getByRole("link", { name: "E-Mail" })).toHaveAttribute(
    "href",
    "mailto:mara.muster@musterwerk.leonaid.invalid",
  );
  // The order context (offers, prices) comes from the device too.
  await page.getByTestId("order-open").click();
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Bestellung für Musterwerk GmbH",
    }),
  ).toBeVisible();
  await expect(page.getByTestId("commitment-quantity")).toBeVisible();
  const results = await analyzeAccessibility(page);
  expect(
    results.violations.filter(({ impact }) =>
      ["critical", "serious"].includes(impact),
    ),
  ).toEqual([]);
  await page.screenshot({
    path: `${artifactDirectory}/pwa-offline-start-${browserName}.png`,
    fullPage: true,
  });

  // Online-only areas (modules) keep the explanation page; the driver's
  // tour (/app/delivery) starts offline since krapfentaxi-touren §9.
  await page.goto(`${baseUrl}/app/tasks`);
  await expect(page).toHaveTitle("LeonAid ist offline");

  // §8.4: the fetch time is authenticated with the copy. An edited clear-
  // text time (to look fresher) makes the copy unusable, not fresh.
  await page.goto(`${baseUrl}/app/sponsors`);
  await expect(page.getByTestId("sponsor-row").first()).toBeVisible();
  await editFetchedAt(page, new Date(Date.now() + 60_000).toISOString());
  await page.reload();
  await expect(page.getByTestId("board-failed-text")).toContainText(
    "Prüfe deine Verbindung.",
  );
  await expect(page.getByTestId("sponsor-row")).toHaveCount(0);

  // Online again, a fresh copy replaces it.
  await context.setOffline(false);
  await page.reload();
  await expect(row).toBeVisible();
  await expect.poll(() => copiesFreshInPage(page)).toBe(true);

  // D3: eight days later (the page's clock), offline, the copy is not
  // shown and capture is blocked.
  await offlineStartReady(page);
  await context.setOffline(true);
  await page.clock.install({ time: Date.now() + 8 * 86_400_000 });
  await page.reload();
  await expect(page.getByTestId("board-failed-text")).toHaveText(
    "Deine Sponsorenliste ist älter als 7 Tage. Geh online, um sie zu aktualisieren.",
  );
  await expect(page.getByTestId("sponsor-row")).toHaveCount(0);

  // Back online, the list is fresh again and replaces the old copy.
  await context.setOffline(false);
  await page.reload();
  await expect(row).toBeVisible();
  await expect.poll(() => copiesFreshInPage(page)).toBe(true);
});

/** Rewrites the clear-text fetch time of every read-cache record. */
function editFetchedAt(page, fetchedAt) {
  return page.evaluate(
    async ([id, value]) => {
      const database = await new Promise((resolve, reject) => {
        const request = indexedDB.open(`leonaid-pwa-v1-${id}`);
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      const transaction = database.transaction("cache", "readwrite");
      const store = transaction.objectStore("cache");
      const records = await new Promise((resolve) => {
        const request = store.getAll();
        request.onsuccess = () => resolve(request.result);
      });
      for (const record of records) store.put({ ...record, fetchedAt: value });
      await new Promise((resolve) => {
        transaction.oncomplete = resolve;
      });
      database.close();
    },
    [ANNA_ID, fetchedAt],
  );
}

/** Every read-cache record was fetched in the last hour, by the page clock. */
function copiesFreshInPage(page) {
  return page.evaluate(async (id) => {
    const database = await new Promise((resolve, reject) => {
      const request = indexedDB.open(`leonaid-pwa-v1-${id}`);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    const result = await new Promise((resolve) => {
      const request = database
        .transaction("cache")
        .objectStore("cache")
        .getAll();
      request.onsuccess = () => resolve(request.result);
    });
    database.close();
    return (
      result.length === 2 &&
      result.every((record) => {
        // Written by this page, not the edited time from the future.
        const age = Date.now() - Date.parse(record.fetchedAt);
        return age >= 0 && age < 3_600_000;
      })
    );
  }, ANNA_ID);
}

test("account switch and sign-out delete the device copy (D6, §8.5)", async ({
  browserName,
  context,
  page,
}) => {
  const second = SECOND_ACQUIRER[browserName];
  test.skip(!second, "No second acquirer persona for this browser.");
  await authenticate(context, annaSession);
  await page.goto(`${baseUrl}/app/sponsors`);
  await expect(page.getByTestId("sponsor-row").first()).toBeVisible();
  await controlled(page);
  await expect
    .poll(() => databaseNames(page), { timeout: 30_000 })
    .toEqual([`leonaid-pwa-v1-${ANNA_ID}`]);

  // Another acquirer signs in on the same device: Anna's data is gone
  // before the other shell renders, without a question.
  await authenticate(context, sessionFor(second.id));
  await page.goto(`${baseUrl}/app/sponsors`);
  await expect(page.getByTestId("display-name")).toHaveText(second.name);
  await expect
    .poll(() => databaseNames(page), { timeout: 30_000 })
    .toEqual([`leonaid-pwa-v1-${second.id}`]);
  expect(
    await page.evaluate(() => localStorage.getItem("leonaid-pwa-active-user")),
  ).toBe(second.id);

  // §12.5: a capture still on the device makes sign-out ask first.
  await controlled(page);
  await expect
    .poll(async () => (await rawDatabase(page, second.id))?.cacheIds.length, {
      timeout: 30_000,
    })
    .toBe(2);
  await context.setOffline(true);
  await page.getByTestId("sponsor-row").first().click();
  await page.getByTestId("contact-open").click();
  await page.locator("#activity-note").fill("Vor dem Abmelden");
  await page.getByTestId("activity-submit").click();
  await page.getByTestId("pwa-menu").click();
  await page.getByTestId("logout").click();
  const warning = page.getByRole("alertdialog", { name: "Abmelden?" });
  await expect(warning).toContainText(
    "Noch 1 Eintrag nicht gesendet. Wenn du dich jetzt abmeldest, wird er von diesem Gerät gelöscht.",
  );
  // Offline there is nothing to send first.
  await expect(warning.getByTestId("sign-out-send-first")).toBeDisabled();
  await warning.getByRole("button", { name: "Abbrechen" }).click();
  await expect(warning).toBeHidden();
  // Back online the queue sends by itself; then sign-out asks nothing.
  await page.keyboard.press("Escape");
  await context.setOffline(false);
  await expect(page.getByTestId("network-state")).toHaveAttribute(
    "data-queue-state",
    "empty",
  );

  // Sign-out deletes everything the PWA kept.
  await page.getByTestId("pwa-menu").click();
  await page.getByTestId("logout").click();
  await expect(page).toHaveURL(/\/login/);
  await expect.poll(() => databaseNames(page)).toEqual([]);
  expect(
    await page.evaluate(() => localStorage.getItem("leonaid-pwa-active-user")),
  ).toBeNull();

  // Without a session and network the app does not start from the cache.
  await context.setOffline(true);
  await page.goto(`${baseUrl}/app/sponsors`);
  await expect(page).toHaveTitle("LeonAid ist offline");
  await context.setOffline(false);
});

test("the admin web app clears the device copy too (D6, §8.5)", async ({
  browserName,
  context,
  page,
}) => {
  // The same forgetDevice() deletion as the PWA sign-out above, which
  // WebKit proves; which app calls it is app logic.
  test.skip(browserName === "webkit", "same deletion as the PWA sign-out");
  test.setTimeout(120_000);
  const KLARA_ID = "10000000-0000-4000-8000-000000000002";
  const openPwa = async () => {
    await authenticate(context, annaSession);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${baseUrl}/app/sponsors`);
    await expect(page.getByTestId("sponsor-row").first()).toBeVisible();
    await controlled(page);
    await expect
      .poll(async () => (await rawDatabase(page, ANNA_ID))?.cacheIds.length, {
        timeout: 30_000,
      })
      .toBe(2);
  };

  // Another person signs in and lands in the admin web app.
  await openPwa();
  await authenticate(context, sessionFor(KLARA_ID));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${baseUrl}/admin/`);
  await expect(page.getByTestId("display-name")).toHaveText(/Klara/);
  await expect.poll(() => databaseNames(page)).toEqual([]);
  expect(
    await page.evaluate(() => localStorage.getItem("leonaid-pwa-active-user")),
  ).toBeNull();
  await context.setOffline(true);
  await page.goto(`${baseUrl}/app/sponsors`);
  await expect(page).toHaveTitle("LeonAid ist offline");
  await context.setOffline(false);

  // Sign-out in the admin web app asks while captures wait (§12.5) and then
  // deletes the copy as well. Klara has no acquirer role, so a copy of hers
  // with one queued record is planted the way the PWA lays it out.
  await page.goto(`${baseUrl}/admin/`);
  await expect(page.getByTestId("display-name")).toHaveText(/Klara/);
  await page.evaluate(async (id) => {
    localStorage.setItem("leonaid-pwa-active-user", id);
    await new Promise((resolve, reject) => {
      const request = indexedDB.open(`leonaid-pwa-v1-${id}`, 1);
      request.onupgradeneeded = () => {
        const database = request.result;
        const queue = database.createObjectStore("queue", {
          keyPath: "entryId",
        });
        queue.createIndex("state", "state");
        queue.createIndex("actionId", "actionId");
        queue.createIndex("sequence", "sequence", { unique: true });
        queue.createIndex("dependsOn", "dependsOn");
        database.createObjectStore("cache", { keyPath: "id" });
        database.createObjectStore("meta", { keyPath: "name" });
        queue.put({ entryId: "planted", sequence: 1, state: "queued" });
      };
      request.onsuccess = () => {
        request.result.close();
        resolve(undefined);
      };
      request.onerror = () => reject(request.error);
    });
  }, KLARA_ID);
  expect(await databaseNames(page)).toEqual([`leonaid-pwa-v1-${KLARA_ID}`]);
  await page.getByTestId("logout").click();
  const warning = page.getByRole("alertdialog", { name: "Abmelden?" });
  await expect(warning).toContainText(
    "In der Akquise-App auf diesem Gerät ist noch 1 Eintrag nicht gesendet.",
  );
  await warning.getByRole("button", { name: "Abbrechen" }).click();
  expect(await databaseNames(page)).toEqual([`leonaid-pwa-v1-${KLARA_ID}`]);
  await page.getByTestId("logout").click();
  await warning.getByTestId("sign-out-anyway").click();
  await expect(page).toHaveURL(/\/login/);
  await expect.poll(() => databaseNames(page)).toEqual([]);
  await context.setOffline(true);
  await page.goto(`${baseUrl}/app/sponsors`);
  await expect(page).toHaveTitle("LeonAid ist offline");
  await context.setOffline(false);
});
