import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const adminSession = process.env.ADMIN_SESSION;
const invoiceId = process.env.INVOICE_ID;
const deliveryId = process.env.DELIVERY_ID;

if (
  !baseUrl ||
  !artifactDirectory ||
  !adminSession ||
  !invoiceId ||
  !deliveryId
) {
  throw new Error("POC-094 Browserumgebung ist unvollständig");
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

test("Charity-Admin sieht SMTP-Ausfall und startet genau diesen Versand neu", async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    ignoreHTTPSErrors: true,
  });
  await context.addCookies([sessionCookie(adminSession)]);
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  try {
    await page.goto(`${baseUrl}/admin/invoices`);
    await expect(
      page.getByRole("heading", { name: "Rechnungen" }),
    ).toBeVisible();
    const invoice = page.locator(`[data-invoice-id="${invoiceId}"]`);
    await expect(invoice).toBeVisible();
    await invoice.locator("summary").click();

    await expect(invoice.getByTestId("invoice-delivery")).toHaveAttribute(
      "data-state",
      "failed",
    );
    await expect(invoice).toContainText("Versand fehlgeschlagen");
    await expect(invoice).toContainText("Letzter Fehler:");
    await expect(invoice).toContainText("1 Versuch");
    await expect(invoice.getByTestId("retry-invoice-delivery")).toBeVisible();
    await page.screenshot({
      path: `${artifactDirectory}/invoice-delivery-failed.png`,
      fullPage: true,
    });

    await invoice.getByTestId("retry-invoice-delivery").click();
    await expect(invoice).toContainText(
      /Wird neu gestartet|In Bearbeitung|Erfolgreich versendet/,
    );
    await expect
      .poll(
        async () =>
          (await invoice
            .getByTestId("invoice-delivery")
            .getAttribute("data-state")) ?? "missing",
        {
          message: "administrativ neu gestarteter SMTP-Versand",
          timeout: 30_000,
          intervals: [100, 200, 400],
        },
      )
      .toBe("sent");

    await expect(invoice).toContainText("Erfolgreich versendet");
    await expect(invoice).toContainText("2 Versuche");
    await expect(
      invoice.getByTestId("invoice-delivery-message-id"),
    ).toContainText("@outbox.leonaid.invalid");
    await expect(invoice.getByTestId("retry-invoice-delivery")).toHaveCount(0);
    await expect(invoice.getByTestId("resend-invoice")).toBeVisible();
    await page.screenshot({
      path: `${artifactDirectory}/invoice-delivery-sent.png`,
      fullPage: true,
    });

    const accessibility = await new AxeBuilder({ page }).analyze();
    expect(
      accessibility.violations.filter(
        (violation) =>
          violation.impact === "critical" || violation.impact === "serious",
      ),
    ).toEqual([]);
    expect(pageErrors).toEqual([]);
    expect(deliveryId).toMatch(/^[0-9a-f-]{36}$/);
  } finally {
    await context.close();
  }
});
