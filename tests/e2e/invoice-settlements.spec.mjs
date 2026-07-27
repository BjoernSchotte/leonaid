import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const klaraSession = process.env.KLARA_SESSION;
const finnSession = process.env.FINN_SESSION;
const openInvoiceId = process.env.OPEN_INVOICE_ID;
const cancellationInvoiceId = process.env.CANCELLATION_INVOICE_ID;
const paymentDate = process.env.PAYMENT_DATE;
const paymentReference = process.env.PAYMENT_REFERENCE;
const cancellationReason = process.env.CANCELLATION_REASON;
const paymentKey = process.env.PAYMENT_KEY;
const cancellationKey = process.env.CANCELLATION_KEY;

if (
  !baseUrl ||
  !artifactDirectory ||
  !klaraSession ||
  !finnSession ||
  !openInvoiceId ||
  !cancellationInvoiceId ||
  !paymentDate ||
  !paymentReference ||
  !cancellationReason ||
  !paymentKey ||
  !cancellationKey
) {
  throw new Error("POC-095 Browserumgebung ist unvollständig");
}

test.setTimeout(90_000);

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

function invoiceRow(page, invoiceId) {
  return page.locator(`[data-invoice-id="${invoiceId}"]`);
}

async function expectNoSeriousAccessibilityViolations(page) {
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(
    accessibility.violations.filter(
      (violation) =>
        violation.impact === "critical" || violation.impact === "serious",
    ),
  ).toEqual([]);
}

test("Charity-Admin verbucht exakt und storniert nachvollziehbar", async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    ignoreHTTPSErrors: true,
  });
  await context.addCookies([sessionCookie(klaraSession)]);
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  try {
    await page.goto(`${baseUrl}/admin/invoices`);
    await expect(
      page.getByRole("heading", { name: "Rechnungen" }),
    ).toBeVisible();
    await expect(page.getByTestId("invoice-row")).toHaveCount(4);
    await expect(page.getByTestId("invoice-profile")).toContainText(
      "Freigabe über Bestellungen",
    );
    await expect(page.getByTestId("invoice-totals")).toContainText("468,00");
    await expect(page.getByTestId("invoice-totals")).toContainText("648,00");

    const open = invoiceRow(page, openInvoiceId);
    const goldenPaid = page
      .getByTestId("invoice-row")
      .filter({ hasText: "KT26-0002" });
    const goldenCancelled = page
      .getByTestId("invoice-row")
      .filter({ hasText: "KT26-0003" });
    await expect(open).toContainText("360,00");
    await expect(goldenPaid).toContainText("Bezahlt");
    await expect(goldenCancelled).toContainText("Storniert");
    await open.locator("summary").click();
    await goldenPaid.locator("summary").click();
    await expect(open.getByTestId("invoice-settlement")).toHaveAttribute(
      "data-state",
      "outstanding",
    );
    await expect(goldenPaid.getByTestId("invoice-settlement")).toHaveAttribute(
      "data-state",
      "paid",
    );
    await page.screenshot({
      path: `${artifactDirectory}/invoice-open-and-paid.png`,
      fullPage: true,
    });

    await open.getByTestId("open-payment-form").click();
    await open.getByTestId("payment-amount").fill("359.99");
    await expect(open.getByRole("alert")).toContainText(
      "exakt dem vollständigen offenen Rechnungsbetrag",
    );
    await expect(open.getByTestId("record-payment")).toBeDisabled();

    await page.evaluate(
      ([invoiceId, key]) => {
        window.sessionStorage.setItem(
          `leonaid.invoice-payment-command.${invoiceId}`,
          key,
        );
      },
      [openInvoiceId, paymentKey],
    );
    await open.getByTestId("payment-amount").fill("360.00");
    await open.getByTestId("payment-date").fill(paymentDate);
    await open.getByTestId("payment-reference").fill(paymentReference);
    await open.getByTestId("record-payment").click();
    await expect(open.getByTestId("invoice-settlement")).toHaveAttribute(
      "data-state",
      "paid",
    );
    await expect(open.getByTestId("payment-record")).toContainText(
      paymentReference,
    );
    await expect(page.getByTestId("invoice-totals")).toContainText("108,00");
    await page.screenshot({
      path: `${artifactDirectory}/invoice-payment-recorded.png`,
      fullPage: true,
    });

    const cancellation = invoiceRow(page, cancellationInvoiceId);
    await cancellation.locator("summary").click();
    await expect(cancellation.getByTestId("invoice-document")).toHaveAttribute(
      "data-state",
      "available",
    );
    await cancellation.getByTestId("open-cancellation-form").click();
    await page.evaluate(
      ([invoiceId, key]) => {
        window.sessionStorage.setItem(
          `leonaid.invoice-cancellation-command.${invoiceId}`,
          key,
        );
      },
      [cancellationInvoiceId, cancellationKey],
    );
    await cancellation
      .getByTestId("cancellation-reason")
      .fill(cancellationReason);
    await cancellation.getByTestId("confirm-cancellation").check();
    await cancellation.getByTestId("cancel-invoice").click();
    await expect(
      cancellation.getByTestId("invoice-settlement"),
    ).toHaveAttribute("data-state", "cancelled");
    await expect(
      cancellation.getByTestId("invoice-cancellation"),
    ).toContainText(cancellationReason);
    await expect(cancellation.getByTestId("invoice-document")).toHaveAttribute(
      "data-state",
      "available",
    );
    await expect(page.getByTestId("invoice-totals")).toContainText("0,00");
    await page.screenshot({
      path: `${artifactDirectory}/invoice-cancellation.png`,
      fullPage: true,
    });

    await expectNoSeriousAccessibilityViolations(page);
    expect(pageErrors).toEqual([]);
  } finally {
    await context.close();
  }
});

test("Finanz-Leser versteht den Status mobil ohne Buchungsrechte", async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    ignoreHTTPSErrors: true,
  });
  await context.addCookies([sessionCookie(finnSession)]);
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  try {
    await page.goto(`${baseUrl}/admin/invoices`);
    await expect(
      page.getByRole("heading", { name: "Rechnungen" }),
    ).toBeVisible();
    await expect(page.getByTestId("invoice-profile")).toContainText(
      "Nur Lesezugriff",
    );
    await expect(page.getByTestId("invoice-row")).toHaveCount(4);
    await expect(page.getByTestId("invoice-totals")).toContainText("0,00");
    await expect(page.getByTestId("open-payment-form")).toHaveCount(0);
    await expect(page.getByTestId("open-cancellation-form")).toHaveCount(0);
    await expect(page.getByTestId("mobile-menu")).toBeVisible();
    await expect(page.getByTestId("desktop-sidebar")).toBeHidden();

    const paid = invoiceRow(page, openInvoiceId);
    const cancelled = invoiceRow(page, cancellationInvoiceId);
    await paid.locator("summary").click();
    await expect(paid.getByTestId("invoice-settlement")).toHaveAttribute(
      "data-state",
      "paid",
    );
    await expect(paid.getByTestId("payment-record")).toContainText(
      paymentReference,
    );
    await page.screenshot({
      path: `${artifactDirectory}/invoice-finance-readonly-mobile.png`,
      fullPage: true,
    });

    await cancelled.locator("summary").click();
    await expect(cancelled.getByTestId("invoice-settlement")).toHaveAttribute(
      "data-state",
      "cancelled",
    );
    await expectNoSeriousAccessibilityViolations(page);
    expect(pageErrors).toEqual([]);
  } finally {
    await context.close();
  }
});
