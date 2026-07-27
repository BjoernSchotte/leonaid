import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const goldenPdfDirectory = process.env.LEONAID_E2E_GOLDEN_PDF_DIR;
const adminSession = process.env.ADMIN_SESSION;
const acquirerSession = process.env.ACQUIRER_SESSION;
const financeSession = process.env.FINANCE_SESSION;
const foreignAdminSession = process.env.FOREIGN_ADMIN_SESSION;
const actionId = "20000000-0000-4000-8000-000000000001";
const foreignActionId = "20000000-0000-4000-8000-000000000003";
const documentId = "90000000-0000-4000-8000-000000000001";
const assignedCompanyId = "40000000-0000-4000-8000-000000000001";

if (
  !baseUrl ||
  !artifactDirectory ||
  !goldenPdfDirectory ||
  !adminSession ||
  !acquirerSession ||
  !financeSession ||
  !foreignAdminSession
) {
  throw new Error("POC-093 Browserumgebung ist unvollständig");
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

async function openDocumentRow(page) {
  await page.goto(`${baseUrl}/admin/invoices`);
  await expect(page.getByRole("heading", { name: "Rechnungen" })).toBeVisible();
  const row = page.getByTestId("invoice-row").filter({ hasText: "KT26-0001" });
  await expect(row).toBeVisible();
  await row.locator("summary").click();
  await expect(row.getByTestId("invoice-document")).toBeVisible();
  await expect(row.getByText("Rechnung-KT26-0001.pdf")).toBeVisible();
  await expect(row.getByTestId("invoice-document-metadata")).toContainText(
    /PDF · .+ · Version 1 · erzeugt/,
  );
  return row;
}

async function expectByteIdenticalDownload(row) {
  const downloadPromise = row.page().waitForEvent("download");
  await row.getByTestId("download-document").click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("Rechnung-KT26-0001.pdf");
  const downloadedPath = await download.path();
  expect(downloadedPath).not.toBeNull();
  const [downloaded, golden] = await Promise.all([
    readFile(downloadedPath),
    readFile(`${goldenPdfDirectory}/KT26-0001.pdf`),
  ]);
  expect(downloaded).toEqual(golden);
}

test("Charity-Admin findet, öffnet und lädt das Typst-PDF byteidentisch", async ({
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
    const row = await openDocumentRow(page);
    await expect(row.getByText("Unveränderliches Rechnungs-PDF")).toBeVisible();
    await expect(row.getByText("Bereit")).toBeVisible();
    await expectByteIdenticalDownload(row);

    const previewPromise = context.waitForEvent("page");
    await row.getByTestId("preview-document").click();
    const preview = await previewPromise;
    const previewFrame = preview.locator("iframe");
    await expect(previewFrame).toHaveAttribute("src", /^blob:/);
    await expect(previewFrame).toHaveAttribute(
      "title",
      "Vorschau Rechnung-KT26-0001.pdf",
    );
    await preview.close();

    await page.screenshot({
      path: `${artifactDirectory}/document-admin-desktop.png`,
      fullPage: true,
    });
    const accessibility = await new AxeBuilder({ page }).analyze();
    expect(
      accessibility.violations.filter(
        (violation) => violation.impact === "critical",
      ),
    ).toEqual([]);
    expect(pageErrors).toEqual([]);
  } finally {
    await context.close();
  }
});

test("Finanzrolle sieht den Beleg mobil, Akquise und Fremdaktion erhalten keine Bytes", async ({
  browser,
}) => {
  const financeContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    ignoreHTTPSErrors: true,
  });
  await financeContext.addCookies([sessionCookie(financeSession)]);
  const financePage = await financeContext.newPage();
  try {
    const row = await openDocumentRow(financePage);
    await expect(financePage.getByTestId("invoice-profile")).toContainText(
      "Nur Lesezugriff",
    );
    await expect(row.getByTestId("preview-document")).toBeVisible();
    await expect(row.getByTestId("download-document")).toBeVisible();
    await expectByteIdenticalDownload(row);
    await financePage.screenshot({
      path: `${artifactDirectory}/document-finance-mobile.png`,
      fullPage: true,
    });
  } finally {
    await financeContext.close();
  }

  const foreignContext = await browser.newContext({
    ignoreHTTPSErrors: true,
  });
  await foreignContext.addCookies([sessionCookie(foreignAdminSession)]);
  try {
    const foreign = await foreignContext.request.get(
      `${baseUrl}/api/v1/actions/${foreignActionId}/documents/${documentId}/download`,
    );
    expect(foreign.status()).toBe(404);
    expect((await foreign.json()).error.code).toBe(
      "generated_document_not_found",
    );
    expect(await foreign.body()).not.toEqual(
      await readFile(`${goldenPdfDirectory}/KT26-0001.pdf`),
    );
  } finally {
    await foreignContext.close();
  }

  const acquirerContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    ignoreHTTPSErrors: true,
  });
  await acquirerContext.addCookies([sessionCookie(acquirerSession)]);
  const acquirerPage = await acquirerContext.newPage();
  try {
    await acquirerPage.goto(`${baseUrl}/admin/invoices`);
    await expect(
      acquirerPage.getByText(
        "Noch keine Charity-Aktion für Finanzen verfügbar",
      ),
    ).toBeVisible();
    await expect(acquirerPage.getByTestId("invoice-document")).toHaveCount(0);
    const companyDocuments = await acquirerContext.request.get(
      `${baseUrl}/api/v1/actions/${actionId}/crm/companies/${assignedCompanyId}/documents`,
    );
    const directDownload = await acquirerContext.request.get(
      `${baseUrl}/api/v1/actions/${actionId}/documents/${documentId}/download`,
    );
    expect(companyDocuments.status()).toBe(403);
    expect((await companyDocuments.json()).error.code).toBe(
      "document_download_required",
    );
    expect(directDownload.status()).toBe(403);
    expect((await directDownload.json()).error.code).toBe(
      "document_download_required",
    );
    expect(await directDownload.body()).not.toEqual(
      await readFile(`${goldenPdfDirectory}/KT26-0001.pdf`),
    );
    await acquirerPage.screenshot({
      path: `${artifactDirectory}/document-acquirer-denied.png`,
      fullPage: true,
    });
  } finally {
    await acquirerContext.close();
  }
});
