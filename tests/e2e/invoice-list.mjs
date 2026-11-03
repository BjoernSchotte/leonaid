// Helpers for the invoice list (ListView rows and the detail pane or sheet).
import { expect } from "@playwright/test";

/** Every visible invoice row. */
export function invoiceRows(page) {
  return page.locator(".listview .row");
}

/** The row link of one invoice, by invoice id or by its number. */
export function invoiceRowLink(page, { id, number }) {
  if (id) {
    return page.locator(".listview .row-link", {
      has: page.locator(`[data-invoice-row="${id}"]`),
    });
  }
  return page.locator(".listview .row-link").filter({ hasText: number });
}

/** The pane (desktop) or sheet (phone) body of the open invoice. */
export function invoicePane(page, id) {
  return id
    ? page.locator(`[data-testid="invoice-detail"][data-invoice-id="${id}"]`)
    : page.getByTestId("invoice-detail");
}

/** Switches the list to a built-in view tab ("Offen", "Alle", …). */
export async function showInvoiceView(page, label) {
  const tab = page
    .getByRole("navigation", { name: "Gespeicherte Ansichten" })
    .getByRole("button", { name: label, exact: true });
  await tab.click();
  await expect(tab).toHaveAttribute("aria-pressed", "true");
}

/** Opens one invoice and returns its pane. */
export async function openInvoice(page, { id, number }) {
  await invoiceRowLink(page, { id, number }).click();
  const pane = id
    ? invoicePane(page, id)
    : page.getByTestId("invoice-detail").filter({ hasText: number });
  await expect(pane).toBeVisible();
  return pane;
}

/** Closes the pane or sheet with Esc. */
export async function closeInvoice(page) {
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("invoice-detail")).toHaveCount(0);
}
