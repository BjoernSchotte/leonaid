import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./csp-guard.mjs";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const mailpitBaseUrl = process.env.LEONAID_E2E_MAILPIT_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const klaraSession = process.env.KLARA_STALE_SESSION;
const finnSession = process.env.FINN_SESSION;
const klaraBulkSession = process.env.KLARA_BULK_SESSION;
const commitmentId = "80000000-0000-4000-8000-000000000002";
const email = "klara.kern@leonaid.invalid";

if (
  !baseUrl ||
  !mailpitBaseUrl ||
  !artifactDirectory ||
  !klaraSession ||
  !klaraBulkSession ||
  !finnSession
) {
  throw new Error("POC-090 browser environment is incomplete");
}

test.setTimeout(90_000);

function recipientAddresses(value) {
  const result = new Set();
  if (typeof value === "string") {
    if (value.includes("@")) result.add(value.toLowerCase());
  } else if (Array.isArray(value)) {
    for (const item of value) {
      for (const address of recipientAddresses(item)) result.add(address);
    }
  } else if (value && typeof value === "object") {
    for (const [key, item] of Object.entries(value)) {
      if (
        ["address", "email"].includes(key.toLowerCase()) &&
        typeof item === "string"
      ) {
        result.add(item.toLowerCase());
      } else {
        for (const address of recipientAddresses(item)) result.add(address);
      }
    }
  }
  return result;
}

async function messageIds(request) {
  const response = await request.get(`${mailpitBaseUrl}/api/v1/messages`);
  expect(response.ok()).toBeTruthy();
  const payload = await response.json();
  return new Set(
    (payload.messages ?? [])
      .map((message) => message.ID)
      .filter((id) => typeof id === "string"),
  );
}

async function waitForCode(request, previousIds) {
  let code;
  await expect
    .poll(
      async () => {
        const response = await request.get(`${mailpitBaseUrl}/api/v1/messages`);
        if (!response.ok()) return "mailpit-unavailable";
        const payload = await response.json();
        for (const summary of payload.messages ?? []) {
          if (
            previousIds.has(summary.ID) ||
            !recipientAddresses(summary.To).has(email)
          ) {
            continue;
          }
          const detailResponse = await request.get(
            `${mailpitBaseUrl}/api/v1/message/${summary.ID}`,
          );
          if (!detailResponse.ok()) continue;
          const detail = await detailResponse.json();
          const match =
            typeof detail.Text === "string"
              ? detail.Text.match(/\bCode ([0-9]{6})\b/)
              : null;
          if (match) {
            code = match[1];
            return "ready";
          }
        }
        return "pending";
      },
      {
        message: "echte Mailpit-Mail mit Fresh-Login-Code",
        timeout: 30_000,
        intervals: [100, 200, 400],
      },
    )
    .toBe("ready");
  return code;
}

function sessionCookie(value) {
  return {
    name: "__Host-leonaid_session",
    value,
    url: baseUrl,
    httpOnly: true,
    secure: true,
    sameSite: "Lax",
  };
}

const actionId = "20000000-0000-4000-8000-000000000001";

async function openCompletion(page) {
  await page.goto(
    `${baseUrl}/admin/orders?status=review_ready&invoice=${commitmentId}`,
  );
  // The order opens in the list's detail pane (a sheet at 390 px).
  const row = page.locator(`[data-commitment-id="${commitmentId}"]`);
  await expect(row).toBeVisible();
  await row.getByTestId("commitment-edit-details").click();
  const form = row.getByTestId("delivery-completion");
  await expect(form).toBeVisible();
  return { form, row };
}

async function fillDelivery(form, contactName) {
  await form
    .getByLabel("Lieferempfänger", { exact: true })
    .fill("Bäckerei Sonnenseite KG, Lager");
  await form
    .getByLabel("Straße und Hausnummer für die Lieferung")
    .fill("Lagerweg 4");
  await form.getByLabel("PLZ für die Lieferung").fill("10243");
  await form.getByLabel("Ort für die Lieferung").fill("Beispielstadt");
  // Every window has passed: the delivery is recorded historically.
  await expect(form).toContainText(
    "Zurzeit ist kein künftiges Lieferfenster verfügbar.",
  );
  const past = form.getByRole("group", {
    name: "Vergangene Lieferzeiten (nachträglich erfassen)",
  });
  await expect(past).toContainText("bereits geliefert");
  const radio = past.getByRole("radio").first();
  await radio.focus();
  await radio.press("Space");
  await expect(radio).toBeChecked();
  await expect(
    form.getByTestId("delivery-completion-historical"),
  ).toBeVisible();
  await form
    .getByLabel("Ansprechpartner bei der Lieferung (optional)")
    .fill(contactName);
}

test("manager records past delivery details historically and recovers from a competing edit", async ({
  browser,
}) => {
  const options = { ignoreHTTPSErrors: true };
  const mobileContext = await browser.newContext({
    ...options,
    viewport: { width: 390, height: 844 },
  });
  const desktopContext = await browser.newContext({
    ...options,
    viewport: { width: 1440, height: 1000 },
  });
  await mobileContext.addCookies([sessionCookie(klaraSession)]);
  await desktopContext.addCookies([sessionCookie(klaraSession)]);
  const page = await mobileContext.newPage();
  const other = await desktopContext.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    const orderUrl = `${baseUrl}/api/v1/actions/${actionId}/commitments/${commitmentId}`;
    const before = await (await page.request.get(orderUrl)).json();
    expect(before.deliveryWindowId).toBeNull();
    const mobile = await openCompletion(page);
    const review = page.getByTestId("invoice-review");
    await expect(review).toContainText("Lieferangaben fehlen");
    await expect(page.getByTestId("issue-invoice")).toBeDisabled();
    await expect(
      mobile.form.getByLabel("Rechnungsempfänger", { exact: true }),
    ).toHaveValue("Bäckerei Sonnenseite KG");
    await fillDelivery(mobile.form, "Lager Süd");
    // The past-window group is accessible and fits 390 px.
    const historicalAccessibility = await new AxeBuilder({ page })
      .include(`[data-commitment-id="${commitmentId}"]`)
      .analyze();
    expect(
      historicalAccessibility.violations.filter((violation) =>
        ["critical", "serious"].includes(violation.impact),
      ),
    ).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `${artifactDirectory}/invoice-delivery-historical-mobile.png`,
      fullPage: true,
    });

    // A second manager completes the same order first.
    const desktop = await openCompletion(other);
    await fillDelivery(desktop.form, "Lager Nord");
    await desktop.form.getByTestId("delivery-completion-submit").click();
    await expect(desktop.form).toContainText("Angaben gespeichert");

    await mobile.form.getByTestId("delivery-completion-submit").click();
    await expect(mobile.form).toContainText("inzwischen geändert");
    await expect(mobile.form).toContainText("Ihre Eingaben bleiben erhalten");
    await expect(
      mobile.form.getByLabel("Ansprechpartner bei der Lieferung (optional)"),
    ).toHaveValue("Lager Süd");
    await mobile.form
      .getByRole("button", { name: "Aktuellen Stand laden und vergleichen" })
      .click();
    const comparison = mobile.form.getByTestId(
      "delivery-completion-comparison",
    );
    await expect(comparison).toContainText("Lager Nord");
    await expect(
      mobile.form.getByTestId("delivery-completion-submit"),
    ).toBeDisabled();
    await comparison
      .getByRole("button", { name: "Meine Eingaben auf diesen Stand anwenden" })
      .click();
    await expect(mobile.form).toContainText(
      "Der gebuchte Liefertermin bleibt unverändert.",
    );
    await mobile.form.getByTestId("delivery-completion-submit").click();
    await expect(mobile.form).toContainText("Angaben gespeichert");

    const readback = await page.request.get(orderUrl);
    expect(readback.ok()).toBeTruthy();
    const order = await readback.json();
    expect(order.status).toBe("review_ready");
    expect(order.deliveryContact.name).toBe("Lager Süd");
    expect(order.deliveryRecipient.streetLine1).toBe("Lagerweg 4");
    // The competing desktop edit booked the window; it stays fixed.
    expect(order.deliveryWindowId).toMatch(/^98000000-/);
    expect(order.deliveryWindowSnapshot.windowId).toBe(order.deliveryWindowId);
    expect(order.invoiceRecipient.streetLine1).toBe("Sonnenstraße 2");
    expect(order.totalMinor).toBe(before.totalMinor);
    expect(order.lines).toEqual(before.lines);

    await expect(review).not.toContainText("Lieferangaben fehlen");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `${artifactDirectory}/invoice-delivery-completion-mobile.png`,
      fullPage: true,
    });
    const accessibility = await new AxeBuilder({ page })
      .include(`[data-commitment-id="${commitmentId}"]`)
      .analyze();
    expect(
      accessibility.violations.filter((violation) =>
        ["critical", "serious"].includes(violation.impact),
      ),
    ).toEqual([]);
    expect(pageErrors).toEqual([]);
  } finally {
    await mobileContext.close();
    await desktopContext.close();
  }
});

test("fresh login protects approval and finance role sees the invoice unchanged", async ({
  browser,
}) => {
  const adminContext = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    ignoreHTTPSErrors: true,
  });
  await adminContext.addCookies([sessionCookie(klaraSession)]);
  const page = await adminContext.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  try {
    await page.goto(`${baseUrl}/admin/orders?invoice=${commitmentId}`);
    await expect(
      page.getByRole("heading", { name: "Bestellungen", exact: true }),
    ).toBeVisible();
    await expect(page.getByTestId("invoice-review")).toBeVisible();
    await expect(page.getByTestId("invoice-review")).toContainText("KT26-0004");
    await expect(page.getByTestId("invoice-review")).toContainText(
      "Bäckerei Sonnenseite KG",
    );
    await expect(
      page.locator(`#invoice-service-help-${commitmentId}`),
    ).toHaveText(/Leistung/);
    await page.screenshot({
      path: `${artifactDirectory}/invoice-review-desktop.png`,
      fullPage: true,
    });

    const previousMailIds = await messageIds(adminContext.request);
    await page.getByTestId("issue-invoice").click();
    await page.waitForURL(/\/fresh-login\?returnTo=/);
    await expect(
      page.getByRole("heading", { name: "Anmeldung bestätigen" }),
    ).toBeVisible();
    await page.getByTestId("request-login").click();
    await expect(page.locator("#complete-login-form")).toBeVisible();
    const freshCode = await waitForCode(adminContext.request, previousMailIds);
    expect(freshCode).toMatch(/^[0-9]{6}$/);
    await page.locator("#login-code").fill(freshCode);
    await page.getByTestId("complete-login").click();
    await page.waitForURL(
      new RegExp(`/admin/orders\\?invoice=${commitmentId}`),
    );

    await expect(page.getByTestId("invoice-review")).toBeVisible();
    await page.getByTestId("issue-invoice").click();
    await expect(
      page.getByText("Rechnung KT26-0004 ist verbindlich freigegeben."),
    ).toBeVisible();

    await page.locator('[data-nav-key="invoices"]').first().click();
    await page.waitForURL(`${baseUrl}/admin/invoices`);
    await expect(
      page.getByRole("heading", { name: "Rechnungen" }),
    ).toBeVisible();
    await expect(page.getByTestId("invoice-profile")).toContainText(
      "Freigegebene Rechtsgrundlage aktiv",
    );
    await expect(page.getByTestId("invoice-row")).toHaveCount(4);
    await expect(page.getByTestId("invoice-totals")).toContainText("648,00");
    const issuedRow = page
      .getByTestId("invoice-row")
      .filter({ hasText: "KT26-0004" });
    await expect(issuedRow).toBeVisible();
    await issuedRow.locator("summary").click();
    await expect(issuedRow).toContainText("Bäckerei Sonnenseite KG");
    await expect(issuedRow).toContainText("Sonnenstraße 2");
    await expect(issuedRow).toContainText(
      "Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.",
    );
    await page.screenshot({
      path: `${artifactDirectory}/invoice-ledger-desktop.png`,
      fullPage: true,
    });

    const accessibility = await new AxeBuilder({ page }).analyze();
    expect(
      accessibility.violations.filter(
        (violation) => violation.impact === "critical",
      ),
    ).toEqual([]);
    expect(pageErrors).toEqual([]);

    await page.getByTestId("theme-trigger").click();
    await page.getByTestId("theme-dark").click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.screenshot({
      path: `${artifactDirectory}/invoice-ledger-dark.png`,
      fullPage: false,
    });
  } finally {
    await adminContext.close();
  }

  const financeContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    ignoreHTTPSErrors: true,
  });
  await financeContext.addCookies([sessionCookie(finnSession)]);
  const financePage = await financeContext.newPage();
  try {
    await financePage.goto(`${baseUrl}/admin/invoices`);
    await expect(
      financePage.getByRole("heading", { name: "Rechnungen" }),
    ).toBeVisible();
    await expect(financePage.getByTestId("invoice-profile")).toContainText(
      "Nur Lesezugriff",
    );
    await expect(financePage.getByTestId("invoice-row")).toHaveCount(4);
    await expect(financePage.getByTestId("issue-invoice")).toHaveCount(0);
    await expect(financePage.getByTestId("mobile-menu")).toBeVisible();
    await expect(financePage.getByTestId("desktop-sidebar")).toBeHidden();
    await financePage.screenshot({
      path: `${artifactDirectory}/invoice-finance-mobile.png`,
      fullPage: true,
    });
    const mobileAccessibility = await new AxeBuilder({
      page: financePage,
    }).analyze();
    expect(
      mobileAccessibility.violations.filter(
        (violation) => violation.impact === "critical",
      ),
    ).toEqual([]);
  } finally {
    await financeContext.close();
  }
});

const bulkOrders = {
  eins: "80000000-0000-4000-8000-0000000000b1",
  zwei: "80000000-0000-4000-8000-0000000000b2",
  drei: "80000000-0000-4000-8000-0000000000b3",
};

test("bulk release issues several invoices with one service date and retries safely", async ({
  browser,
}) => {
  // A finance reader cannot issue: no bulk release on the orders page.
  const financeContext = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    ignoreHTTPSErrors: true,
  });
  await financeContext.addCookies([sessionCookie(finnSession)]);
  try {
    const financePage = await financeContext.newPage();
    await financePage.goto(
      `${baseUrl}/admin/orders?action=${actionId}&view=all`,
    );
    await expect(
      financePage.getByRole("heading", { name: "Bestellungen", exact: true }),
    ).toBeVisible();
    await expect(financePage.getByTestId("bulk-release-open")).toHaveCount(0);
    await expect(financePage.locator(".listview li.row")).toHaveCount(0);
  } finally {
    await financeContext.close();
  }

  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    ignoreHTTPSErrors: true,
  });
  await context.addCookies([sessionCookie(klaraBulkSession)]);
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  const issuePath = (id) =>
    `**/api/v1/actions/${actionId}/commitments/${id}/invoice`;
  // "Drei": the server refuses this order (e.g. changed meanwhile).
  await page.route(issuePath(bulkOrders.drei), (route) =>
    route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({
        error: {
          code: "invoice_commitment_not_review_ready",
          message: "Die Bestellung ist nicht mehr prüfbereit.",
          requestId: "e2e-bulk",
        },
      }),
    }),
  );
  // "Zwei": the server issues the invoice, but the answer is lost once.
  let zweiAnswers = 0;
  await page.route(issuePath(bulkOrders.zwei), async (route) => {
    const response = await route.fetch();
    if (response.ok() && zweiAnswers === 0) {
      zweiAnswers += 1;
      await route.abort("connectionreset");
      return;
    }
    await route.fulfill({ response });
  });

  try {
    await page.goto(`${baseUrl}/admin/orders?action=${actionId}&view=all`);
    for (const name of [
      "Sammel Eins KG",
      "Sammel Zwei KG",
      "Sammel Drei KG",
      "Doppelkontakt AG",
    ]) {
      await page
        .getByRole("checkbox", { name: new RegExp(`^${name} ·`) })
        .check();
    }
    const open = page.getByTestId("bulk-release-open");
    await expect(open).toContainText("3 von 4 freigebbar");
    await open.click();
    const dialog = page.getByRole("dialog", { name: "Rechnungen freigeben" });
    await expect(dialog.locator("[data-release-id]")).toHaveCount(3);
    await expect(dialog.getByTestId("bulk-release-total")).toHaveText(
      "324,00 €",
    );
    await expect(dialog).toContainText(
      "Doppelkontakt AG (Rechnungsadresse fehlt)",
    );
    const serviceOn = await dialog
      .getByTestId("bulk-release-service-on")
      .inputValue();
    expect(serviceOn).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    const accessibility = await new AxeBuilder({ page })
      .include(".bulk-release")
      .analyze();
    expect(
      accessibility.violations.filter((violation) =>
        ["critical", "serious"].includes(violation.impact),
      ),
    ).toEqual([]);
    await page.screenshot({
      path: `${artifactDirectory}/invoice-bulk-release-desktop.png`,
    });

    // The stale session asks for the fresh sign-in first, then resumes.
    const previousMailIds = await messageIds(context.request);
    await dialog
      .getByRole("button", { name: "3 Rechnungen verbindlich ausstellen" })
      .click();
    await page.waitForURL(/\/fresh-login\?returnTo=/);
    await page.getByTestId("request-login").click();
    await expect(page.locator("#complete-login-form")).toBeVisible();
    const code = await waitForCode(context.request, previousMailIds);
    await page.locator("#login-code").fill(code);
    await page.getByTestId("complete-login").click();
    await page.waitForURL(/\/admin\/orders\?/);
    await expect(dialog.locator("[data-release-id]")).toHaveCount(3);
    await expect(dialog.getByTestId("bulk-release-service-on")).toHaveValue(
      serviceOn,
    );

    // The list order is newest first: Drei, Zwei, Eins. Drei is refused and
    // the run goes on; the answer for Zwei is lost, so the run stops there.
    await dialog
      .getByRole("button", { name: "3 Rechnungen verbindlich ausstellen" })
      .click();
    const result = page.getByRole("dialog", { name: "Ergebnis der Freigabe" });
    const failed = result.getByTestId("bulk-release-failed");
    await expect(failed).toContainText(
      "Sammel Drei KG: Die Bestellung ist nicht mehr prüfbereit.",
    );
    const unfinished = result.getByTestId("bulk-release-open");
    await expect(unfinished).toContainText("Sammel Zwei KG: Keine Antwort");
    await expect(unfinished).toContainText("Sammel Eins KG: nicht gesendet.");
    const issued = result.getByTestId("bulk-release-issued");
    await expect(issued).toContainText("Ausgestellt (0)");
    expect(zweiAnswers).toBe(1);

    // The retry replays Zwei's key (no second invoice) and issues Eins.
    await result
      .getByRole("button", { name: "2 Rechnungen erneut senden" })
      .click();
    await expect(issued).toContainText("Ausgestellt (2)");
    await expect(issued).toContainText("Sammel Zwei KG");
    await expect(issued).toContainText("Sammel Eins KG");
    await expect(failed).toContainText("Sammel Drei KG");
    await expect(unfinished).toHaveCount(0);
    const shownNumbers = await issued.locator("a").allTextContents();
    expect(shownNumbers).toHaveLength(2);
    await page.screenshot({
      path: `${artifactDirectory}/invoice-bulk-release-result.png`,
    });

    const invoices = await (
      await page.request.get(`${baseUrl}/api/v1/actions/${actionId}/invoices`)
    ).json();
    const numbersFor = (commitment) =>
      invoices.items
        .filter((item) => item.invoice.commitmentId === commitment)
        .map((item) => item.invoice.number);
    expect(numbersFor(bulkOrders.eins)).toHaveLength(1);
    expect(numbersFor(bulkOrders.zwei)).toHaveLength(1);
    expect(numbersFor(bulkOrders.drei)).toHaveLength(0);
    expect(shownNumbers.sort()).toEqual(
      [...numbersFor(bulkOrders.eins), ...numbersFor(bulkOrders.zwei)].sort(),
    );
    const allNumbers = invoices.items.map((item) => item.invoice.number);
    expect(new Set(allNumbers).size).toBe(allNumbers.length);
    for (const item of invoices.items.filter((entry) =>
      [bulkOrders.eins, bulkOrders.zwei].includes(entry.invoice.commitmentId),
    ))
      expect(item.invoice.serviceOn).toBe(serviceOn);

    await result
      .locator(".modal-footer")
      .getByRole("button", { name: "Schließen" })
      .click();
    await expect(result).toHaveCount(0);
    const einsRow = page.locator(".listview li.row", {
      has: page.locator(`[data-order-id="${bulkOrders.eins}"]`),
    });
    await expect(einsRow).toContainText("Fakturiert");
    expect(pageErrors).toEqual([]);
  } finally {
    await context.close();
  }
});
