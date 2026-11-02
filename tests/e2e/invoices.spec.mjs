import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./csp-guard.mjs";

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
  const row = page.locator(`[data-commitment-id="${commitmentId}"]`);
  await expect(row).toBeVisible();
  await row.getByTestId("commitment-order-details").locator("summary").click();
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
  await form.getByRole("radio").first().check();
  await form
    .getByLabel("Ansprechpartner bei der Lieferung (optional)")
    .fill(contactName);
}

test("manager completes missing delivery details and recovers from a competing edit", async ({
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

    // A second manager completes the same order first.
    const desktop = await openCompletion(other);
    await fillDelivery(desktop.form, "Lager Nord");
    await desktop.form.getByTestId("delivery-completion-submit").click();
    await expect(desktop.form).toContainText("Angaben gespeichert");

    await mobile.form.getByTestId("delivery-completion-submit").click();
    await expect(mobile.form).toContainText("inzwischen geändert");
    await expect(mobile.form).toContainText("Deine Eingaben bleiben erhalten");
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
    expect(order.deliveryWindowId).toBe("98000000-0000-4000-8000-000000000002");
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
      path: `${artifactDirectory}/delivery-completion-mobile.png`,
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
