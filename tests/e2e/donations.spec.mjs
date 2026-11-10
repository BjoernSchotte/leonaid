import { analyzeAccessibility } from "./axe.mjs";
import { expect, test } from "./csp-guard.mjs";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const adminSession = process.env.ADMIN_SESSION;
const financeSession = process.env.FINANCE_SESSION;

if (!baseUrl || !artifactDirectory || !adminSession || !financeSession) {
  throw new Error("Donation browser environment is incomplete");
}

test.setTimeout(120_000);

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

// tools/documents/contract.py recorded SP26-0001 before this spec and proved
// its PDF and its mail. Here a manager works in the browser: record a
// donation, see its pledge, book what arrived, take it back.
test("a manager records a donation, gets the pledge and books the payment", async ({
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
    await page.goto(`${baseUrl}/admin/`);
    // The navigation offers "Spenden" because the action takes donations.
    await page.getByRole("link", { name: "Spenden" }).first().click();
    await expect(page).toHaveURL(/\/admin\/donations/);
    await expect(page.getByTestId("donation-receiving-body")).toContainText(
      "Förderverein Lions Club Musterstadt e. V.",
    );
    await expect(page.getByText("SP26-0001")).toBeVisible();

    await page
      .getByRole("button", { name: /Spende erfassen/ })
      .first()
      .click();
    const form = page.getByTestId("donation-form");
    await form.getByTestId("donation-donor-name").fill("Elektro Blitz GmbH");
    await form.getByTestId("donation-donor-street").fill("Werkstraße 7");
    await form.getByTestId("donation-donor-postal-code").fill("12345");
    await form.getByTestId("donation-donor-city").fill("Musterstadt");
    await form.getByTestId("donation-amount").fill("50");
    await page.screenshot({
      path: `${artifactDirectory}/donation-create.png`,
      fullPage: true,
    });
    await page.getByTestId("create-donation").click();
    await expect(page.getByText("Spende SP26-0002 erfasst.")).toBeVisible();
    await expect(page.getByTestId("donation-pledged-open-total")).toContainText(
      "100,00 €",
    );

    await page.getByText("SP26-0002").first().click();
    const detail = page.getByTestId("donation-detail");
    await expect(detail).toHaveAttribute("data-status", "pledged");
    // The worker renders the pledge; the list polls until it is there.
    await expect(detail.getByTestId("donation-pledge-document")).toContainText(
      "Spendenzusage-SP26-0002.pdf",
      { timeout: 60_000 },
    );
    // No e-mail address was given: the pledge cannot be mailed.
    await expect(
      detail.getByTestId("donation-donor-email-missing"),
    ).toBeVisible();
    await expect(detail.getByTestId("send-donation-pledge")).toHaveCount(0);
    const download = page.waitForEvent("download");
    await detail.getByTestId("download-donation-pledge").click();
    expect((await download).suggestedFilename()).toBe(
      "Spendenzusage-SP26-0002.pdf",
    );

    // More arrived than was pledged: what arrived counts.
    await detail.getByTestId("open-donation-payment-form").click();
    const payment = page.getByTestId("donation-payment-form");
    await expect(payment.getByTestId("donation-payment-amount")).toHaveValue(
      "50,00",
    );
    await payment.getByTestId("donation-payment-amount").fill("60,00");
    await page.getByTestId("record-donation-payment").click();
    await expect(detail).toHaveAttribute("data-status", "paid");
    await expect(detail.getByTestId("donation-payment")).toContainText(
      "10,00 € mehr als zugesagt",
    );
    await expect(page.getByTestId("donation-received-total")).toContainText(
      "60,00 €",
    );
    // A paid donation is not cancelled.
    await expect(detail.getByTestId("donation-paid-no-cancel")).toBeVisible();
    await expect(
      detail.getByTestId("open-donation-cancellation-form"),
    ).toHaveCount(0);
    const accessibility = await analyzeAccessibility(page);
    expect(accessibility.violations).toEqual([]);
    await page.screenshot({
      path: `${artifactDirectory}/donation-paid.png`,
      fullPage: true,
    });

    await detail.getByTestId("open-donation-withdrawal-form").click();
    await page
      .getByTestId("donation-withdrawal-reason")
      .fill("Zahlung gehörte zu einer anderen Spende");
    await page.getByTestId("withdraw-donation-payment").click();
    await expect(detail).toHaveAttribute("data-status", "pledged");
    await expect(detail.getByTestId("donation-payment")).toContainText(
      "Zahlung gehörte zu einer anderen Spende",
    );
    await expect(page.getByTestId("donation-received-total")).toContainText(
      "0,00 €",
    );
    expect(pageErrors).toEqual([]);
  } finally {
    await context.close();
  }
});

test("a finance reader sees the donations and no command", async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    ignoreHTTPSErrors: true,
  });
  await context.addCookies([sessionCookie(financeSession)]);
  const page = await context.newPage();
  try {
    await page.goto(`${baseUrl}/admin/donations`);
    await expect(page.getByTestId("donation-read-only")).toBeVisible();
    await expect(page.getByText("SP26-0001")).toBeVisible();
    await expect(
      page.getByRole("button", { name: /Spende erfassen/ }),
    ).toHaveCount(0);
    await page.getByText("SP26-0001").first().click();
    const detail = page.getByTestId("donation-detail");
    await expect(detail.getByTestId("donation-pledge-document")).toContainText(
      "Spendenzusage-SP26-0001.pdf",
    );
    await expect(detail.getByTestId("open-donation-payment-form")).toHaveCount(
      0,
    );
    await expect(detail.getByTestId("send-donation-pledge")).toHaveCount(0);
  } finally {
    await context.close();
  }
});
