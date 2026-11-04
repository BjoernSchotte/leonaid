// Helpers for the material list (expandable rows, upload dialog).
import { expect } from "@playwright/test";

/** The row of one material, by its exact title. */
export function materialRow(page, title) {
  return page.locator(".materials .material", {
    has: page.locator(".material-title").getByText(title, { exact: true }),
  });
}

/** Uploads a new material from the list page and waits for its row. */
export async function uploadMaterial(page, baseURL, shell, { title, file }) {
  await page.goto(`${baseURL}${shell}/materials`);
  await page
    .getByRole("button", { name: "Material hochladen", exact: true })
    .first()
    .click();
  const dialog = page.getByRole("dialog", { name: "Material hochladen" });
  await dialog.getByLabel("Materialtitel").fill(title);
  await dialog.getByLabel("Datei").setInputFiles(file);
  await dialog.getByRole("button", { name: "Hochladen", exact: true }).click();
  await expect(dialog).toBeHidden();
  const row = materialRow(page, title);
  await expect(row).toBeVisible();
  return row;
}
