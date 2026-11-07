// Offline queue stage 1 (specs/pwa-offline-queue §8, §16): with the flag
// pwa.offline_queue on, the PWA starts without network from the cached
// shell, shows the acquirer's own sponsors and the order context from the
// encrypted device copy, and clears the device on account switch and
// sign-out. Runs against the real stack (tools/pwa/test.sh switches the
// flag on before and off after this spec); no request is intercepted.
import { analyzeAccessibility } from "./axe.mjs";
import { expect, test } from "./csp-guard.mjs";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const annaSession = process.env.ANNA_SESSION;

if (!baseUrl || !artifactDirectory || !annaSession) {
  throw new Error(
    "LEONAID_E2E_BASE_URL, LEONAID_E2E_ARTIFACT_DIR und ANNA_SESSION sind erforderlich",
  );
}

const ANNA_ID = "10000000-0000-4000-8000-000000000004";
const BERND_ID = "10000000-0000-4000-8000-000000000005";
// tools/pwa/contract.py prepares these sessions for the PWA personas.
const berndSession = `poc062-${BERND_ID}-server-session-token-value`;

test.use({
  ignoreHTTPSErrors: true,
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
            Boolean(
              (await navigator.serviceWorker.getRegistration())?.active,
            ),
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
  test.setTimeout(120_000);
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
  expect(raw.metaNames).toEqual(["device-key", "identity", "offlineEnabled"]);
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

  // Online-only areas keep the explanation page.
  await page.goto(`${baseUrl}/app/delivery`);
  await expect(page).toHaveTitle("LeonAid ist offline");

  // D3: a sponsor list older than 7 days is not shown offline.
  await page.goto(`${baseUrl}/app/sponsors`);
  await expect(page.getByTestId("sponsor-row").first()).toBeVisible();
  await page.evaluate(async (id) => {
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
    const old = new Date(Date.now() - 8 * 86_400_000).toISOString();
    for (const record of records) store.put({ ...record, fetchedAt: old });
    await new Promise((resolve) => {
      transaction.oncomplete = resolve;
    });
    database.close();
  }, ANNA_ID);
  await page.reload();
  await expect(page.getByTestId("board-failed-text")).toHaveText(
    "Deine Sponsorenliste ist älter als 7 Tage. Geh online, um sie zu aktualisieren.",
  );
  await expect(page.getByTestId("sponsor-row")).toHaveCount(0);

  // Back online, the list is fresh again and replaces the old copy.
  await context.setOffline(false);
  await page.reload();
  await expect(row).toBeVisible();
  await expect
    .poll(async () => {
      const records = await page.evaluate(async (id) => {
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
        return result.map((record) => record.fetchedAt);
      }, ANNA_ID);
      return records.every(
        (value) => Date.now() - Date.parse(value) < 3_600_000,
      );
    })
    .toBe(true);
});

test("account switch and sign-out delete the device copy (D6, §8.5)", async ({
  context,
  page,
}) => {
  test.setTimeout(120_000);
  await authenticate(context, annaSession);
  await page.goto(`${baseUrl}/app/sponsors`);
  await expect(page.getByTestId("sponsor-row").first()).toBeVisible();
  await controlled(page);
  await expect
    .poll(() => databaseNames(page), { timeout: 30_000 })
    .toEqual([`leonaid-pwa-v1-${ANNA_ID}`]);

  // Another acquirer signs in on the same device: Anna's data is gone
  // before Bernd's shell renders, without a question.
  await authenticate(context, berndSession);
  await page.goto(`${baseUrl}/app/sponsors`);
  await expect(page.getByTestId("display-name")).toHaveText(/Bernd/);
  await expect
    .poll(() => databaseNames(page), { timeout: 30_000 })
    .toEqual([`leonaid-pwa-v1-${BERND_ID}`]);
  expect(
    await page.evaluate(() => localStorage.getItem("leonaid-pwa-active-user")),
  ).toBe(BERND_ID);

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
