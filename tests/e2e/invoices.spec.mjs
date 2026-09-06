import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const mailpitBaseUrl = process.env.LEONAID_E2E_MAILPIT_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const klaraSession = process.env.KLARA_STALE_SESSION;
const finnSession = process.env.FINN_SESSION;
const commitmentId = "80000000-0000-4000-8000-000000000002";
const email = "klara.kern@leonaid.invalid";

if (
  !baseUrl ||
  !mailpitBaseUrl ||
  !artifactDirectory ||
  !klaraSession ||
  !finnSession
) {
  throw new Error("POC-090 Browserumgebung ist unvollständig");
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

test("Fresh Login schützt Freigabe und Finanzrolle sieht den Beleg unveränderlich", async ({
  browser,
}) => {
  let adminCookies;
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
      page.getByRole("heading", { name: "Bestellungen prüfen" }),
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
    adminCookies = await adminContext.cookies();
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
  await completeDeliveryInBrowser(browser, adminCookies);
});

async function completeDeliveryInBrowser(browser, cookies) {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 390, height: 844 },
  });
  await context.addCookies(cookies);
  try {
    const root = `${baseUrl}/api/v1/actions/20000000-0000-4000-8000-000000000001`;
    const listing = await context.request.get(`${root}/commitments`);
    expect(listing.ok()).toBeTruthy();
    const source = (await listing.json()).items[0].commitment;
    const created = await context.request.post(`${root}/commitments`, {
      headers: { "Idempotency-Key": crypto.randomUUID() },
      data: {
        source: "admin",
        readyForReview: false,
        buyer: source.buyer,
        lines: source.lines.map((line) => ({
          offeringId: line.offeringId,
          quantity: 1,
          unit: line.unit,
        })),
      },
    });
    expect(created.ok()).toBeTruthy();
    const order = await created.json();
    const configResponse = await context.request.get(`${root}/delivery`);
    const config = await configResponse.json();
    delete config.actionId;
    const slot = crypto.randomUUID();
    config.enabled = true;
    config.windows.push({
      id: crypto.randomUUID(),
      deliveryOn: "2026-10-02",
      startsAt: "09:00",
      endsAt: "11:00",
      retired: false,
    });
    config.windows.push({
      id: slot,
      deliveryOn: "2026-09-02",
      startsAt: "09:00",
      endsAt: "11:00",
      retired: true,
    });
    expect(
      (await context.request.put(`${root}/delivery`, { data: config })).ok(),
    ).toBeTruthy();
    const actionResponse = await context.request.get(root);
    const action = await actionResponse.json();
    const completedAction = await context.request.post(`${root}/transitions`, {
      data: { revision: action.revision, targetStatus: "completed" },
    });
    expect(completedAction.ok()).toBeTruthy();
    expect((await completedAction.json()).status).toBe("completed");
    const definitionResponse = await context.request.get(
      `${root}/delivery/order-form`,
    );
    expect(definitionResponse.ok()).toBeTruthy();
    expect(definitionResponse.headers()["cache-control"]).toContain("no-store");
    expect(
      (await definitionResponse.json()).windows.some(
        (item) => item.id === slot,
      ),
    ).toBeFalsy();
    const page = await context.newPage();
    await page.goto(`${baseUrl}/admin/orders`);
    const row = page.locator(`[data-commitment-id="${order.id}"]`);
    await row.getByRole("button", { name: "Lieferdaten ergänzen" }).click();
    const form = row.getByTestId("delivery-completion");
    await expect(
      form.getByRole("heading", {
        name: "Liefer- und Rechnungsdaten ergänzen",
      }),
    ).toBeFocused();
    await form.getByRole("button", { name: "Ergänzung schließen" }).click();
    await expect(
      row.getByRole("button", { name: "Lieferdaten ergänzen" }),
    ).toBeFocused();
    await row.getByRole("button", { name: "Lieferdaten ergänzen" }).click();
    await form
      .getByLabel("Firma / Empfänger", { exact: true })
      .fill("Lieferkontakt UI");
    await form
      .getByLabel("Straße und Hausnummer", { exact: true })
      .fill("Lieferweg 4");
    await form.getByLabel("PLZ", { exact: true }).fill("86150");
    await form.getByLabel("Ort", { exact: true }).fill("Augsburg");
    const confirmation = form.getByLabel(
      "Ich bestätige den ausgewählten vergangenen Liefertermin als historischen Nachtrag.",
    );
    await expect(confirmation).not.toBeChecked();
    await confirmation.check();
    await expect(form.getByLabel("Liefertag", { exact: true })).toHaveValue("");
    await form
      .getByLabel("Liefertag", { exact: true })
      .selectOption("2026-09-02");
    await form
      .getByLabel("Lieferzeitfenster", { exact: true })
      .selectOption(slot);
    await form
      .getByLabel("Abteilung / Lieferhinweise (optional)")
      .fill("Abteilung UI\nStock 4");
    await form
      .getByLabel("Rechnungsadresse entspricht der Lieferadresse")
      .uncheck();
    await form
      .getByLabel("Rechnungsempfänger", { exact: true })
      .fill("Rechnung UI");
    await form
      .getByLabel("Straße und Hausnummer (Rechnung)", { exact: true })
      .fill("Rechnungsweg 8");
    await form.getByLabel("PLZ (Rechnung)", { exact: true }).fill("86150");
    await form.getByLabel("Ort (Rechnung)", { exact: true }).fill("Augsburg");
    await form
      .getByLabel("Rechnungs-E-Mail", { exact: true })
      .fill("invoice-ui@example.invalid");
    const accessibility = await new AxeBuilder({ page })
      .include('[data-testid="delivery-completion"]')
      .analyze();
    expect(
      accessibility.violations.filter((v) =>
        ["critical", "serious"].includes(v.impact),
      ),
    ).toEqual([]);
    const overflow = await page.evaluate(() =>
      [...document.querySelectorAll('[data-testid="delivery-completion"] *')]
        .filter(
          (element) =>
            element.getBoundingClientRect().right > window.innerWidth + 1,
        )
        .map((element) => ({
          tag: element.tagName,
          class: element.className,
          right: element.getBoundingClientRect().right,
        })),
    );
    expect(overflow).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBeTruthy();
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "200%";
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBeTruthy();
    await expect(
      form.getByRole("button", { name: "Ergänzen und prüfbereit speichern" }),
    ).toBeVisible();
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "";
    });
    await page.screenshot({
      path: `${artifactDirectory}/invoice-delivery-completion.png`,
      fullPage: true,
    });
    const concurrentlySaved = await context.request.post(
      `${root}/commitments/${order.id}/delivery-completion`,
      {
        headers: { "Idempotency-Key": crypto.randomUUID() },
        data: {
          expectedVersion: order.deliveryCompletionVersion,
          windowId: slot,
          confirmHistoricalDelivery: true,
          deliveryRecipient: {
            recipientName: "Parallel gespeichert",
            streetLine1: "Parallelweg 1",
            postalCode: "86150",
            city: "Augsburg",
            countryCode: "DE",
          },
          invoiceRecipient: {
            recipientName: "Parallel Rechnung",
            streetLine1: "Parallelweg 2",
            postalCode: "86150",
            city: "Augsburg",
            countryCode: "DE",
          },
        },
      },
    );
    expect(concurrentlySaved.ok()).toBeTruthy();
    await form
      .getByRole("button", { name: "Ergänzen und prüfbereit speichern" })
      .click();
    await expect(form.getByRole("alert")).toContainText("inzwischen geändert");
    await expect(
      form.getByLabel("Firma / Empfänger", { exact: true }),
    ).toHaveValue("Lieferkontakt UI");
    await form
      .getByRole("button", { name: "Aktuelle Angaben vergleichen" })
      .click();
    await expect(
      form.getByRole("region", { name: "Gespeicherte Angaben" }),
    ).toContainText("Parallel gespeichert");
    await form
      .getByRole("button", {
        name: "Eigene Eingaben auf diesen Stand übernehmen",
      })
      .click();
    const completionUrl = `${root}/commitments/${order.id}/delivery-completion`;
    let acceptedCompletion;
    let submittedKey;
    let interceptedCompletions = 0;
    const loseCompletionResponse = async (route) => {
      interceptedCompletions += 1;
      submittedKey = route.request().headers()["idempotency-key"];
      const accepted = await route.fetch();
      expect(accepted.ok()).toBeTruthy();
      acceptedCompletion = await accepted.json();
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ error: {
          code: "response_unavailable",
          requestId: "completion-response-loss-proof",
          message: "Die Antwort konnte nicht zugestellt werden.",
        } }),
      });
    };
    await page.route(completionUrl, loseCompletionResponse);
    const saveCompletion = form.getByRole("button", {
      name: "Ergänzen und prüfbereit speichern",
    });
    await saveCompletion.click();
    await expect(form.getByRole("alert")).toContainText("nicht zugestellt");
    const deliveryName = form.getByLabel("Firma / Empfänger", { exact: true });
    await expect(deliveryName).toHaveValue("Lieferkontakt UI");
    await deliveryName.fill("Geänderte unbekannte Übermittlung");
    await saveCompletion.click();
    await expect(form.getByRole("alert")).toContainText("Ausgang der letzten Übermittlung ist unklar");
    expect(interceptedCompletions).toBe(1);
    await deliveryName.fill("Lieferkontakt UI");
    await page.unroute(completionUrl, loseCompletionResponse);
    const [retried] = await Promise.all([
      page.waitForResponse((response) => response.url() === completionUrl && response.request().method() === "POST"),
      saveCompletion.click(),
    ]);
    expect(retried.ok()).toBeTruthy();
    expect(retried.request().headers()["idempotency-key"]).toBe(submittedKey);
    const replayedCompletion = await retried.json();
    expect(replayedCompletion.id).toBe(acceptedCompletion.id);
    expect(replayedCompletion.deliveryCompletionVersion).toBe(acceptedCompletion.deliveryCompletionVersion);
    await expect(form).toHaveCount(0);
    await expect(row).toContainText("Prüfbereit");
    await expect(
      row.getByRole("button", { name: "Lieferdaten ergänzen" }),
    ).toBeFocused();
    await row
      .getByText("Liefer- und Rechnungsdaten ansehen", { exact: true })
      .click();
    await expect(row).toContainText("Abteilung UI");
    const savedListing = await context.request.get(`${root}/commitments`);
    const saved = (await savedListing.json()).items.find(
      (item) => item.commitment.id === order.id,
    ).commitment;
    expect(saved.invoiceRecipient.recipientName).toBe("Rechnung UI");
    expect(saved.invoiceRecipient.streetLine1).toBe("Rechnungsweg 8");
    expect(saved.deliveryWindowId).toBe(slot);
    expect(saved.totalMinor).toBe(order.totalMinor);
  } finally {
    await context.close();
  }
}
