import { analyzeAccessibility } from "./axe.mjs";
import { expect, test } from "./csp-guard.mjs";
import {
  closeInvoice,
  invoiceRow,
  invoiceRows,
  openInvoice,
  showInvoiceView,
} from "./invoice-list.mjs";

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
  throw new Error("POC-095 browser environment is incomplete");
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

async function expectNoSeriousAccessibilityViolations(page) {
  const accessibility = await analyzeAccessibility(page);
  expect(
    accessibility.violations.filter(
      (violation) =>
        violation.impact === "critical" || violation.impact === "serious",
    ),
  ).toEqual([]);
}

test("charity admin books partial and full payments and reverses an entry", async ({
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
    await expect(page.getByTestId("invoice-read-only")).toHaveCount(0);
    await expect(page.getByTestId("invoice-open-total")).toContainText(
      "468,00",
    );
    await showInvoiceView(page, "Alle");
    await expect(invoiceRows(page)).toHaveCount(4);

    const openRow = invoiceRow(page, openInvoiceId);
    await expect(openRow).toContainText("360,00");
    await expect(
      page.locator(".listview .row").filter({ hasText: "KT26-0002" }),
    ).toContainText("Bezahlt");
    await expect(
      page.locator(".listview .row").filter({ hasText: "KT26-0003" }),
    ).toContainText("Storniert");

    const goldenPaid = await openInvoice(page, { number: "KT26-0002" });
    await expect(goldenPaid).toHaveAttribute("data-settlement", "paid");
    await expect(goldenPaid.getByTestId("invoice-stamp")).toContainText(
      "Bezahlt",
    );
    const open = await openInvoice(page, { id: openInvoiceId });
    await expect(open).toHaveAttribute("data-settlement", "outstanding");
    await page.screenshot({
      path: `${artifactDirectory}/invoice-open-and-paid.png`,
      fullPage: true,
    });

    // A partial payment: the amount starts as the open remainder.
    await open.getByTestId("open-payment-form").click();
    const paymentDialog = page.getByRole("dialog", {
      name: /Zahlung für .* erfassen/,
    });
    await expect(paymentDialog).toBeVisible();
    await expect(paymentDialog.getByTestId("payment-amount")).toHaveValue(
      "360,00",
    );
    await paymentDialog.getByTestId("payment-amount").fill("100,00");
    await expect(paymentDialog).toContainText("Danach bleiben 260,00");
    await paymentDialog.getByTestId("payment-date").fill(paymentDate);
    await paymentDialog
      .getByTestId("payment-note")
      .fill("Anzahlung per Überweisung");
    await paymentDialog.getByTestId("record-payment").click();
    await expect(paymentDialog).toBeHidden();
    await expect(open).toHaveAttribute("data-settlement", "partial");
    await expect(open.getByTestId("invoice-open-amount")).toContainText(
      "260,00",
    );
    await expect(page.getByTestId("invoice-open-total")).toContainText(
      "368,00",
    );
    const partialEntry = open
      .getByTestId("payment-entry")
      .filter({ hasText: "Anzahlung per Überweisung" });
    await expect(partialEntry).toHaveCount(1);
    await page.screenshot({
      path: `${artifactDirectory}/invoice-partial-payment.png`,
      fullPage: true,
    });

    // Reverse the partial entry: it stays, struck through, outside the sum.
    await partialEntry.getByTestId("open-reversal-form").click();
    const reversalDialog = page.getByRole("alertdialog", {
      name: /zurückbuchen\?/,
    });
    await expect(reversalDialog).toBeVisible();
    await reversalDialog
      .getByTestId("reversal-reason")
      .fill("Betrag gehört zu einer anderen Rechnung");
    await reversalDialog.getByTestId("reverse-payment").click();
    await expect(reversalDialog).toBeHidden();
    await expect(open).toHaveAttribute("data-settlement", "outstanding");
    await expect(partialEntry.getByTestId("open-reversal-form")).toHaveCount(0);
    await expect(partialEntry).toContainText(
      "Betrag gehört zu einer anderen Rechnung",
    );
    await expect(page.getByTestId("invoice-open-total")).toContainText(
      "468,00",
    );

    // The full payment stays one click on the prefilled remainder.
    await page.evaluate(
      ([invoiceId, key]) => {
        window.sessionStorage.setItem(
          `leonaid.invoice-payment-command.${invoiceId}`,
          key,
        );
      },
      [openInvoiceId, paymentKey],
    );
    await open.getByTestId("open-payment-form").click();
    await expect(paymentDialog).toBeVisible();
    await expect(paymentDialog.getByTestId("payment-amount")).toHaveValue(
      "360,00",
    );
    await paymentDialog.getByTestId("payment-date").fill(paymentDate);
    await paymentDialog.getByTestId("payment-reference").fill(paymentReference);
    await paymentDialog.getByTestId("record-payment").click();
    await expect(paymentDialog).toBeHidden();
    await expect(open).toHaveAttribute("data-settlement", "paid");
    await expect(open.getByTestId("invoice-stamp")).toContainText("Bezahlt");
    await expect(open.getByTestId("payment-record")).toContainText(
      paymentReference,
    );
    await expect(page.getByTestId("invoice-open-total")).toContainText(
      "108,00",
    );
    await page.screenshot({
      path: `${artifactDirectory}/invoice-payment-recorded.png`,
      fullPage: true,
    });

    const cancellation = await openInvoice(page, {
      id: cancellationInvoiceId,
    });
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
    const cancelDialog = page.getByRole("alertdialog", {
      name: /stornieren\?/,
    });
    await expect(cancelDialog).toBeVisible();
    await cancelDialog
      .getByTestId("cancellation-reason")
      .fill(cancellationReason);
    await cancelDialog.getByTestId("cancel-invoice").click();
    await expect(cancelDialog).toBeHidden();
    await expect(cancellation).toHaveAttribute("data-settlement", "cancelled");
    await expect(cancellation.getByTestId("invoice-stamp")).toContainText(
      "Storniert",
    );
    await expect(
      cancellation.getByTestId("invoice-cancellation"),
    ).toContainText(cancellationReason);
    await expect(cancellation.getByTestId("invoice-document")).toHaveAttribute(
      "data-state",
      "available",
    );
    await expect(page.getByTestId("invoice-open-total")).toContainText("0,00");
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

test("finance reader understands the status on mobile without booking rights", async ({
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
    await expect(page.getByTestId("invoice-read-only")).toContainText(
      "Nur lesen.",
    );
    await expect(page.getByTestId("invoice-open-total")).toContainText("0,00");
    await showInvoiceView(page, "Alle");
    await expect(invoiceRows(page)).toHaveCount(4);
    await expect(page.getByTestId("mobile-menu")).toBeVisible();
    await expect(page.getByTestId("desktop-sidebar")).toBeHidden();

    const paid = await openInvoice(page, { id: openInvoiceId });
    await expect(paid).toHaveAttribute("data-settlement", "paid");
    await expect(paid.getByTestId("open-payment-form")).toHaveCount(0);
    await expect(paid.getByTestId("open-cancellation-form")).toHaveCount(0);
    await expect(paid.getByTestId("payment-record")).toContainText(
      paymentReference,
    );
    await page.screenshot({
      path: `${artifactDirectory}/invoice-finance-readonly-mobile.png`,
      fullPage: true,
    });

    await closeInvoice(page);
    const cancelled = await openInvoice(page, { id: cancellationInvoiceId });
    await expect(cancelled).toHaveAttribute("data-settlement", "cancelled");
    await expect(cancelled.getByTestId("invoice-stamp")).toContainText(
      "Storniert",
    );
    await expect(cancelled.getByTestId("open-cancellation-form")).toHaveCount(
      0,
    );
    await expectNoSeriousAccessibilityViolations(page);
    expect(pageErrors).toEqual([]);
  } finally {
    await context.close();
  }
});
