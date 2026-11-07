// Offline queue stage 3 (specs/pwa-offline-queue §9, §12): with the flag
// on, a contact and an order captured without network are kept encrypted
// on the device, survive a reload and are sent once, automatically, when
// the network returns. Real stack, no interception (tools/pwa/test.sh
// switches the flag on for the offline specs only).
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

const ACTION_ID = "20000000-0000-4000-8000-000000000001";

test.use({
  ignoreHTTPSErrors: true,
  launchOptions:
    process.env.LEONAID_E2E_BROWSER === "chromium"
      ? { args: ["--ignore-certificate-errors"] }
      : {},
  viewport: { width: 390, height: 844 },
});

async function authenticate(context) {
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
}

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

/** Clear-text index and the sealed value of every queue record. */
function rawQueue(page) {
  return page.evaluate(async () => {
    const userId = localStorage.getItem("leonaid-pwa-active-user");
    const database = await new Promise((resolve, reject) => {
      const request = indexedDB.open(`leonaid-pwa-v1-${userId}`);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    const records = await new Promise((resolve) => {
      const request = database
        .transaction("queue")
        .objectStore("queue")
        .getAll();
      request.onsuccess = () => resolve(request.result);
    });
    database.close();
    return records.map((record) => ({
      clearText: new TextDecoder("utf-8", { fatal: false }).decode(
        record.sealed.data,
      ),
      index: Object.keys(record).sort(),
      state: record.state,
    }));
  });
}

async function apiJson(page, path) {
  const response = await page.request.get(`${baseUrl}${path}`);
  expect(response.ok()).toBe(true);
  return response.json();
}

test("captures made offline are kept on the device and sent once online", async ({
  browserName,
  context,
  page,
}) => {
  test.setTimeout(180_000);
  await authenticate(context);
  await page.goto(`${baseUrl}/app/sponsors`);
  const row = page
    .getByTestId("sponsor-row")
    .filter({ hasText: "Musterwerk GmbH" });
  await expect(row).toBeVisible();
  await controlled(page);
  const indicator = page.getByTestId("network-state");
  await expect(indicator).toHaveAccessibleName("Online");

  // Offline: the banner promises what the queue now does (§12.1).
  await context.setOffline(true);
  await page.reload();
  const banner = page.getByTestId("offline-banner");
  await expect(banner).toContainText(
    "Neue Kontakte, Wiedervorlagen und Bestellungen speichert LeonAid auf diesem Gerät",
  );

  // A contact attempt with a note and a follow-up.
  const note = `Offline erfasst ${browserName} ${Date.now()}`;
  await row.click();
  await page.getByTestId("contact-open").click();
  const sheet = page.getByTestId("contact-sheet");
  await sheet.getByText("Erreicht", { exact: true }).click();
  await page.locator("#activity-note").fill(note);
  await page.getByTestId("activity-submit").click();
  await expect(
    page.getByText(
      "Kontakt gespeichert. Wird gesendet, sobald du wieder online bist.",
    ),
  ).toBeVisible();
  await expect(indicator).toHaveAccessibleName("1 Eintrag wartet auf Versand");
  await expect(banner).toContainText("1 wartet auf Versand.");
  await expect(page.getByTestId("pending-capture")).toContainText(
    "Wartet auf Verbindung",
  );

  // An order as draft, also offline.
  await page.getByTestId("order-open").click();
  await page.getByTestId("commitment-quantity").fill("2");
  await page.getByRole("button", { name: "Weiter" }).click();
  await page.getByTestId("commitment-street").fill("Offlineweg 7");
  await page.locator("#commitment-postal-code").fill("80331");
  await page.locator("#commitment-city").fill("München");
  await page.getByRole("button", { name: "Weiter" }).click();
  await page.getByTestId("commitment-save-draft").click();
  await expect(page.getByTestId("commitment-queued")).toContainText(
    "Bestellung gespeichert",
  );
  await expect(indicator).toHaveAccessibleName("2 Einträge warten auf Versand");

  // §8.4: the queue holds no clear text, the index no personal data.
  const records = await rawQueue(page);
  expect(records).toHaveLength(2);
  for (const record of records) {
    expect(record.index).toEqual([
      "actionId",
      "dependsOn",
      "entryId",
      "sealed",
      "sequence",
      "state",
    ]);
    for (const secret of [note, "Musterwerk", "Offlineweg"]) {
      expect(record.clearText).not.toContain(secret);
    }
  }

  // The queue survives a reload without network.
  await page.reload();
  await expect(indicator).toHaveAccessibleName("2 Einträge warten auf Versand");
  await indicator.click();
  const queueSheet = page.getByTestId("queue-sheet");
  await expect(queueSheet).toBeVisible();
  await expect(queueSheet.getByTestId("queue-entry")).toHaveCount(2);
  await expect(queueSheet).toContainText("Kontakt mit Musterwerk GmbH");
  await expect(queueSheet).toContainText("Bestellung für Musterwerk GmbH");
  await expect(queueSheet.getByTestId("queue-send-now")).toBeDisabled();
  const results = await analyzeAccessibility(page);
  expect(
    results.violations.filter(({ impact }) =>
      ["critical", "serious"].includes(impact),
    ),
  ).toEqual([]);
  await page.screenshot({
    path: `${artifactDirectory}/pwa-offline-queue-${browserName}.png`,
    fullPage: true,
  });
  await page.keyboard.press("Escape");

  // Back online: sent without a tap, each once.
  await context.setOffline(false);
  await expect(indicator).toHaveAccessibleName("Online", { timeout: 30_000 });
  expect(await rawQueue(page)).toEqual([]);
  const board = await apiJson(
    page,
    `/api/v1/actions/${ACTION_ID}/acquisition/activity-board?limit=100`,
  );
  const recorded = board.activities.filter((item) => item.note === note);
  expect(recorded).toHaveLength(1);
  // D5: the contact happened when it was captured, not when it arrived.
  expect(Date.parse(recorded[0].occurredAt)).toBeLessThan(Date.now() - 1_000);
  // The order list is for the action's managers; tools/pwa/test.sh
  // checks the stored drafts (one per browser run) in PostgreSQL.
  // The sheet keeps "Gesendet" for this page life (§8.5).
  await indicator.click();
  await expect(
    page.getByTestId("queue-sheet").getByTestId("queue-state"),
  ).toHaveText(["Gesendet", "Gesendet"]);
  await page.keyboard.press("Escape");
  // The sponsor's history shows the contact once.
  await page.goto(`${baseUrl}/app/sponsors`);
  await row.click();
  await expect(
    page.getByTestId("activity-entry").filter({ hasText: note }),
  ).toHaveCount(1);
});
