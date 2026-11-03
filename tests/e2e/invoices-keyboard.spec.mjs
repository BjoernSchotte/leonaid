import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./csp-guard.mjs";
import { invoiceRows, showInvoiceView } from "./invoice-list.mjs";

// Runs in the invoice settlement stack (tools/invoice_settlements/test.sh):
// four golden invoices for Klara (charity admin) and Finn (finance reader).
const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const klaraSession = process.env.KLARA_SESSION;

if (!baseUrl || !artifactDirectory || !klaraSession) {
  throw new Error("Invoice keyboard browser environment is incomplete");
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

async function expectNoSeriousAccessibilityViolations(page, label) {
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(
    accessibility.violations
      .filter(
        (violation) =>
          violation.impact === "critical" || violation.impact === "serious",
      )
      .map((violation) => `${label}: ${violation.id}`),
  ).toEqual([]);
}

test("invoice list: j/k, Enter, Esc, x and read-only status by keyboard", async ({
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
      page.getByRole("heading", { level: 1, name: "Rechnungen" }),
    ).toBeVisible();
    await showInvoiceView(page, "Alle");
    const rows = page.locator(".listview .row-link");
    await expect(invoiceRows(page)).toHaveCount(4);
    // The status is read-only: no letter key in the hint, no chip menu.
    await expect(page.locator(".list-hint")).not.toContainText("Status");
    await expect(page.locator('[data-chip="status"]')).toHaveCount(0);
    await page.locator("body").click({ position: { x: 5, y: 5 } });

    // j/k move the focus, Enter opens the pane, Esc closes it again.
    await page.keyboard.press("j");
    await page.keyboard.press("j");
    await page.keyboard.press("k");
    await expect(rows.first()).toBeFocused();
    await page.keyboard.press("Enter");
    const pane = page.getByRole("complementary", { name: /^Details: KT26-/ });
    await expect(pane).toBeVisible();
    await expect(pane.getByTestId("invoice-detail")).toBeVisible();
    await expect(page).toHaveURL(/[?&]open=[0-9a-f-]{36}/);
    await expect(pane.locator(".pane-props")).toHaveCount(0);
    await expectNoSeriousAccessibilityViolations(page, "Rechnung im Detail");

    // j in the open pane shows the next invoice.
    const firstTitle = await pane.locator(".pane-title").textContent();
    await page.keyboard.press("j");
    await expect(rows.nth(1)).toBeFocused();
    await expect(pane.locator(".pane-title")).not.toHaveText(firstTitle ?? "");
    await page.keyboard.press("Escape");
    await expect(pane).toHaveCount(0);
    await expect(rows.nth(1)).toBeFocused();
    await expect(page).not.toHaveURL(/[?&]open=/);

    // x checks rows; the bulk bar has no status edit; Esc clears.
    await page.keyboard.press("x");
    await page.keyboard.press("k");
    await page.keyboard.press("x");
    const bulk = page.getByRole("region", { name: "Auswahl" });
    await expect(bulk).toContainText("2 ausgewählt");
    await expect(bulk.getByRole("button", { name: /Status/ })).toHaveCount(0);
    await page.keyboard.press("Escape");
    await expect(bulk).toHaveCount(0);

    // f filters by status; the URL keeps it.
    await page.keyboard.press("f");
    const filterMenu = page.getByRole("dialog", { name: "Filter wählen" });
    await expect(filterMenu.getByRole("combobox")).toBeFocused();
    await page.keyboard.type("Stat");
    await page.keyboard.press("Enter");
    const statusMenu = page.getByRole("dialog", { name: "Filter Status" });
    await expect(statusMenu.getByRole("combobox")).toBeFocused();
    await statusMenu.getByRole("option", { name: /Storniert/ }).click();
    await page.keyboard.press("Escape");
    await expect(statusMenu).toHaveCount(0);
    await expect(page).toHaveURL(/f\.status=cancelled/);
    await expect(invoiceRows(page).first()).toBeVisible();
    await expect(
      invoiceRows(page).filter({ hasNotText: "Storniert" }),
    ).toHaveCount(0);
    await page.screenshot({
      path: `${artifactDirectory}/invoice-keyboard-filter.png`,
      fullPage: false,
    });

    // The palette leads to the payments ledger of the same action.
    await page.keyboard.press("Control+k");
    const palette = page.getByRole("dialog", { name: "Befehlspalette" });
    await expect(palette).toBeVisible();
    await page.keyboard.type("Zahlungen ansehen");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/admin\/invoices\/payments\?action=/);
    await expect(
      page.getByRole("heading", { level: 1, name: "Zahlungen" }),
    ).toBeVisible();
    await expect(page.getByTestId("payments-table")).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Rechnungen", exact: true }),
    ).toHaveAttribute("href", /\/admin\/invoices\?action=/);
    await expectNoSeriousAccessibilityViolations(page, "Zahlungen");
    expect(pageErrors).toEqual([]);
  } finally {
    await context.close();
  }
});
