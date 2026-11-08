// Offline queue stage 4 (specs/pwa-offline-queue §10): the acquirer's
// decisions. A follow-up captured offline meets a newer one from another
// device (D1: the contact is kept, the follow-up is a decision), and a new
// sponsor saved offline is checked online with the match step, after which
// its contact is sent. Real stack, no interception.
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

const ACTION_ID = "20000000-0000-4000-8000-000000000001";

// The board reads the CRM, which Core limits to 100 requests a minute for
// the whole installation; after the heavier specs a first load can wait.
test.describe.configure({ timeout: 240_000 });

test.use({
  ignoreHTTPSErrors: true,
  launchOptions:
    process.env.LEONAID_E2E_BROWSER === "chromium"
      ? { args: ["--ignore-certificate-errors"] }
      : {},
  viewport: { width: 390, height: 844 },
});

async function signIn(context) {
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

/** Waits until the device copy of the sponsor list and order context exists. */
async function deviceCopyReady(page) {
  await expect
    .poll(
      () =>
        page.evaluate(async () => {
          const userId = localStorage.getItem("leonaid-pwa-active-user");
          if (!userId) return [];
          const names = (await indexedDB.databases()).map((item) => item.name);
          if (!names.includes(`leonaid-pwa-v1-${userId}`)) return [];
          const database = await new Promise((resolve, reject) => {
            const request = indexedDB.open(`leonaid-pwa-v1-${userId}`);
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
          });
          const ids = await new Promise((resolve) => {
            const request = database
              .transaction("cache")
              .objectStore("cache")
              .getAllKeys();
            request.onsuccess = () => resolve(request.result);
          });
          database.close();
          return ids.map((id) => id.split(":")[0]).sort();
        }),
      { timeout: 30_000 },
    )
    .toEqual(["board", "capture"]);
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

async function board(page) {
  const response = await page.request.get(
    `${baseUrl}/api/v1/actions/${ACTION_ID}/acquisition/activity-board?limit=100`,
    { timeout: 60_000 },
  );
  expect(response.ok()).toBe(true);
  return response.json();
}

async function recordContact(page, { outcome, note, nextAction }) {
  await page.getByTestId("contact-open").click();
  const sheet = page.getByTestId("contact-sheet");
  await sheet.getByText(outcome, { exact: true }).click();
  if (nextAction) await page.locator("#activity-next-action").fill(nextAction);
  await page.locator("#activity-note").fill(note);
  await page.getByTestId("activity-submit").click();
}

test("a follow-up that met a newer one is the acquirer's decision (D1)", async ({
  browser,
  browserName,
  context,
  page,
}) => {
  await signIn(context);
  await page.goto(`${baseUrl}/app/sponsors`);
  const row = page
    .getByTestId("sponsor-row")
    .filter({ hasText: "Musterwerk GmbH" });
  await expect(row).toBeVisible();
  await controlled(page);
  await deviceCopyReady(page);

  // Offline on this phone: a contact with a follow-up.
  await context.setOffline(true);
  await page.reload();
  await row.click();
  const mine = `Meine Wiedervorlage ${browserName}`;
  const note = `Offline mit Wiedervorlage ${browserName} ${Date.now()}`;
  await recordContact(page, {
    nextAction: mine,
    note,
    outcome: "Später nachfassen",
  });
  await expect(page.getByTestId("network-state")).toHaveAccessibleName(
    "1 Eintrag wartet auf Versand",
  );

  // Meanwhile, on another device, a newer follow-up for the same sponsor.
  const other = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 390, height: 844 },
  });
  await signIn(other);
  const otherPage = await other.newPage();
  await otherPage.goto(`${baseUrl}/app/sponsors`);
  await otherPage
    .getByTestId("sponsor-row")
    .filter({ hasText: "Musterwerk GmbH" })
    .click();
  const theirs = `Andere Wiedervorlage ${browserName}`;
  await recordContact(otherPage, {
    nextAction: theirs,
    note: `Zweites Gerät ${browserName}`,
    outcome: "Später nachfassen",
  });
  await expect(otherPage.getByText("Kontakt erfasst.")).toBeVisible();
  await other.close();

  // Back online: the contact is stored, the follow-up asks.
  await context.setOffline(false);
  const indicator = page.getByTestId("network-state");
  await expect(indicator).toHaveAccessibleName(
    "1 Eintrag braucht deine Entscheidung",
    { timeout: 30_000 },
  );
  expect(
    (await board(page)).activities.filter((item) => item.note === note),
  ).toHaveLength(1);
  await indicator.click();
  const entry = page
    .getByTestId("queue-sheet")
    .locator('[data-testid="queue-entry"][data-state="conflict"]');
  await expect(entry.getByTestId("queue-state")).toHaveText(
    "Braucht deine Entscheidung",
  );
  await expect(entry.getByTestId("queue-reason")).toContainText(
    `Dein Kontakt mit Musterwerk GmbH ist gespeichert. Die Wiedervorlage wurde nicht übernommen, weil inzwischen jemand anderes etwas eingetragen hat: ${theirs}`,
  );
  const results = await analyzeAccessibility(page);
  expect(
    results.violations.filter(({ impact }) =>
      ["critical", "serious"].includes(impact),
    ),
  ).toEqual([]);
  await page.screenshot({
    path: `${artifactDirectory}/pwa-offline-decision-${browserName}.png`,
    fullPage: true,
  });
  await entry
    .getByRole("button", { name: "Meine Wiedervorlage übernehmen" })
    .click();
  await expect(indicator).toHaveAccessibleName("Online");
  const musterwerk = (await board(page)).workItems.find(
    (item) => item.partyDisplayName === "Musterwerk GmbH",
  );
  expect(musterwerk.nextAction).toBe(mine);
});

test("a sponsor saved offline is checked online, then its contact goes out (D10)", async ({
  browserName,
  context,
  page,
}) => {
  await signIn(context);
  await page.goto(`${baseUrl}/app/sponsors?view=new`);
  await expect(page.getByTestId("sponsor-preview")).toBeVisible();
  await controlled(page);
  await deviceCopyReady(page);

  await context.setOffline(true);
  await page.reload();
  const company = `Offline Bäckerei ${browserName} ${Date.now()}`;
  await page.getByTestId("sponsor-draft-company").fill(company);
  await page.locator("#sponsor-draft-city").fill("Augsburg");
  // The street stays off the device.
  await expect(
    page.locator("#sponsor-draft-form [name=streetLine1]"),
  ).toHaveCount(0);
  await page.getByTestId("sponsor-draft-save").click();
  await expect(page.getByTestId("sponsor-draft-saved")).toContainText(
    "Entwurf gespeichert",
  );
  const note = `Kontakt zum Entwurf ${browserName}`;
  await page.getByTestId("sponsor-draft-contact").click();
  await page
    .getByTestId("contact-sheet")
    .getByText("Interessiert", { exact: true })
    .click();
  await page.locator("#activity-note").fill(note);
  await page.getByTestId("activity-submit").click();

  const indicator = page.getByTestId("network-state");
  await expect(indicator).toHaveAccessibleName(
    "1 Eintrag braucht deine Entscheidung",
  );

  // Online: nothing goes out until the acquirer checked the draft.
  await context.setOffline(false);
  await indicator.click();
  const sheet = page.getByTestId("queue-sheet");
  await expect(sheet).toContainText(
    `Neuer Sponsor ${company} wartet auf deine Prüfung. 1 Eintrag wartet darauf.`,
  );
  await sheet.getByTestId("queue-check-draft").click();
  // The form opens with the draft's values; the street can be added
  // before the CRM check (#132 M2).
  await expect(page.getByTestId("sponsor-draft-check")).toBeVisible();
  await expect(page.getByTestId("sponsor-company")).toHaveValue(company);
  await page.locator("#sponsor-street").fill("Unterwegsstraße 9");
  await page.getByTestId("sponsor-preview").click();
  await page.getByTestId("sponsor-resolve").click();
  await expect(page.locator("#sponsor-status")).toContainText(
    `${company} ist jetzt dir zugeordnet.`,
  );
  await expect(indicator).toHaveAccessibleName("Online", { timeout: 30_000 });
  const after = await board(page);
  const sponsor = after.workItems.find(
    (item) => item.partyDisplayName === company,
  );
  expect(sponsor).toBeTruthy();
  const contacts = after.activities.filter((item) => item.note === note);
  expect(contacts).toHaveLength(1);
  expect(contacts[0].partyId).toBe(sponsor.partyId);
});

/** Asks tools/pwa/test.sh for a database change and waits until it is done. */
async function serverChange(name) {
  const { existsSync, rmSync, writeFileSync } = await import("node:fs");
  const done = `${artifactDirectory}/offline-done-${name}`;
  rmSync(done, { force: true });
  writeFileSync(`${artifactDirectory}/offline-request-${name}`, "");
  await baseExpect.poll(() => existsSync(done), { timeout: 30_000 }).toBe(true);
}

/** Order for Musterwerk up to the review step; delivery when asked. */
async function fillOrder(page, { delivery }) {
  await page
    .getByTestId("sponsor-row")
    .filter({ hasText: "Musterwerk GmbH" })
    .click();
  await page.getByTestId("order-open").click();
  await page.getByTestId("commitment-quantity").fill("1");
  await page.getByRole("button", { name: "Weiter" }).click();
  await page.getByTestId("commitment-street").fill("Entscheidungsweg 3");
  await page.locator("#commitment-postal-code").fill("80331");
  await page.locator("#commitment-city").fill("München");
  if (delivery) {
    await page
      .getByText("Lieferadresse wie Rechnungsadresse übernehmen")
      .click();
    await page.locator('input[name="delivery-window"]').first().check();
  }
  await page.getByRole("button", { name: "Weiter" }).click();
}

test("a window booked out meanwhile asks in the queue (§10.2, §10.3)", async ({
  context,
  page,
}) => {
  await serverChange("window-setup");
  try {
    await signIn(context);
    await page.goto(`${baseUrl}/app/sponsors`);
    await expect(page.getByTestId("sponsor-row").first()).toBeVisible();
    await controlled(page);
    await deviceCopyReady(page);
    await context.setOffline(true);
    await page.reload();
    await fillOrder(page, { delivery: true });
    await page.getByTestId("commitment-save-ready").click();
    await expect(page.getByTestId("commitment-queued")).toBeVisible();

    await serverChange("window-full");
    await context.setOffline(false);
    const indicator = page.getByTestId("network-state");
    await expect(indicator).toHaveAccessibleName(
      "1 Eintrag braucht deine Entscheidung",
    );
    await indicator.click();
    const entry = page
      .getByTestId("queue-sheet")
      .locator('[data-testid="queue-entry"][data-state="conflict"]');
    await expect(entry.getByTestId("queue-reason")).toContainText("ausgebucht");
    // The way out exists (#132 M1), and booking anyway keeps the key.
    await expect(
      entry.getByRole("button", { name: "Verwerfen" }),
    ).toBeVisible();
    await entry.getByRole("button", { name: "Trotzdem eintragen" }).click();
    await expect(indicator).toHaveAttribute("data-queue-state", "empty");
  } finally {
    await serverChange("window-teardown");
  }
});

test("a price changed meanwhile asks in the queue (§10.2)", async ({
  context,
  page,
}) => {
  await signIn(context);
  await page.goto(`${baseUrl}/app/sponsors`);
  await expect(page.getByTestId("sponsor-row").first()).toBeVisible();
  await controlled(page);
  await deviceCopyReady(page);
  await context.setOffline(true);
  await page.reload();
  await fillOrder(page, { delivery: false });
  await page.getByTestId("commitment-save-draft").click();
  await expect(page.getByTestId("commitment-queued")).toBeVisible();

  await serverChange("price-up");
  try {
    await context.setOffline(false);
    const indicator = page.getByTestId("network-state");
    await expect(indicator).toHaveAccessibleName(
      "1 Eintrag braucht deine Entscheidung",
    );
    await indicator.click();
    const entry = page
      .getByTestId("queue-sheet")
      .locator('[data-testid="queue-entry"][data-state="conflict"]');
    await expect(entry.getByTestId("queue-reason")).toContainText(
      "Der Preis ist jetzt",
    );
    await entry.getByRole("button", { name: "Neuen Preis übernehmen" }).click();
    await expect(indicator).toHaveAttribute("data-queue-state", "empty");
  } finally {
    await serverChange("price-down");
  }
});

test("'Trotzdem abmelden' deletes what still waits (§12.5)", async ({
  context,
  page,
}) => {
  await signIn(context);
  await page.goto(`${baseUrl}/app/sponsors`);
  await controlled(page);
  await deviceCopyReady(page);
  await context.setOffline(true);
  await page
    .getByTestId("sponsor-row")
    .filter({ hasText: "Musterwerk GmbH" })
    .click();
  await page.getByTestId("contact-open").click();
  await page.locator("#activity-note").fill("Wird gelöscht");
  await page.getByTestId("activity-submit").click();
  await page.getByTestId("pwa-menu").click();
  await page.getByTestId("logout").click();
  const warning = page.getByRole("alertdialog", { name: "Abmelden?" });
  await expect(warning).toContainText("Noch 1 Eintrag nicht gesendet.");
  // Offline the sign-out request cannot reach Core; the device is cleared
  // first anyway.
  await warning.getByTestId("sign-out-anyway").click();
  await context.setOffline(false);
  await page.goto(`${baseUrl}/login`);
  await expect
    .poll(() =>
      page.evaluate(async () =>
        (await indexedDB.databases())
          .map((item) => item.name)
          .filter((name) => name.startsWith("leonaid-pwa-v1-")),
      ),
    )
    .toEqual([]);
});
