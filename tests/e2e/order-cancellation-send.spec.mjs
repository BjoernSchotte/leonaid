import { expect, test } from "./csp-guard.mjs";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const adminSession = process.env.ADMIN_SESSION;
const commitmentId = process.env.COMMITMENT_ID;

if (!baseUrl || !artifactDirectory || !adminSession || !commitmentId) {
  throw new Error("Order cancellation browser environment is incomplete");
}

test.setTimeout(90_000);

// The order's invoice was sent by mail (invoice-delivery.spec.mjs). Its
// cancellation in the order dialog offers to send the cancellation invoice
// to the same address; tools/invoice_delivery/contract.py then proves the
// mail.
test("cancelling an order whose invoice was mailed offers to send the cancellation invoice", async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    ignoreHTTPSErrors: true,
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: adminSession,
      url: baseUrl,
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
    },
  ]);
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  try {
    await page.goto(`${baseUrl}/admin/orders?view=all&open=${commitmentId}`);
    await page.getByTestId("open-order-cancellation").click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toContainText("wird mitstorniert.");
    const send = dialog.getByTestId("send-invoice-cancellation-with-order");
    // On by default, with the address the invoice went to.
    await expect(send).toBeChecked();
    await expect(dialog).toContainText("Stornorechnung gleich senden");
    await expect(dialog).toContainText("@");
    await dialog
      .getByTestId("order-cancellation-reason")
      .fill("Sponsor hat die Bestellung zurückgezogen");
    await page.screenshot({
      path: `${artifactDirectory}/order-cancellation-send-dialog.png`,
      fullPage: true,
    });
    await dialog.getByTestId("cancel-order").click();
    await expect(dialog).toBeHidden();
    await expect(
      page.getByText(/Stornorechnung KT26-\d{4} wurde ausgestellt\./),
    ).toBeVisible();
    await page.screenshot({
      path: `${artifactDirectory}/order-cancellation-sent.png`,
      fullPage: true,
    });
    expect(pageErrors).toEqual([]);
  } finally {
    await context.close();
  }
});
