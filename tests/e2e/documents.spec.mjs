import { analyzeAccessibility } from "./axe.mjs";
import { expect, test } from "./csp-guard.mjs";
import { invoiceListHeading, openInvoice } from "./invoice-list.mjs";
import { readFile } from "node:fs/promises";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const goldenPdfDirectory = process.env.LEONAID_E2E_GOLDEN_PDF_DIR;
const adminSession = process.env.ADMIN_SESSION;
// Chromium's built-in PDF viewer extension.
const CHROMIUM_PDF_VIEWER_ORIGIN =
  "chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/";

if (!baseUrl || !artifactDirectory || !goldenPdfDirectory || !adminSession) {
  throw new Error("POC-093 browser environment is incomplete");
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
  await page.goto(`${baseUrl}/admin/invoices?view=all`);
  await expect(invoiceListHeading(page)).toBeVisible();
  const row = await openInvoice(page, { number: "KT26-0001" });
  await expect(row.getByTestId("invoice-document")).toHaveAttribute(
    "data-state",
    "available",
  );
  await expect(row.getByText("Rechnung-KT26-0001.pdf")).toBeVisible();
  await expect(row.getByTestId("invoice-document-metadata")).toContainText(
    /PDF · .+ · Version 2 · erzeugt/,
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

async function expectStableTopLevelPreview(context, row) {
  const crashes = [];
  context.on("page", (candidate) => {
    candidate.on("crash", () => crashes.push(candidate.url()));
  });
  const previewLink = row.getByTestId("preview-document");
  const previewHref = await previewLink.getAttribute("href");
  expect(previewHref).toMatch(
    /^\/api\/v1\/actions\/.+\/documents\/.+\/download\?inline=true$/,
  );

  const response = await context.request.get(
    new URL(previewHref, baseUrl).toString(),
  );
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toContain("application/pdf");
  expect(response.headers()["content-disposition"]).toContain("inline");
  expect((await response.body()).subarray(0, 5).toString()).toBe("%PDF-");

  const previewPromise = context.waitForEvent("page");
  await previewLink.click();
  const preview = await previewPromise;
  await preview.waitForURL(new URL(previewHref, baseUrl).toString());
  expect(await preview.evaluate(() => document.contentType)).toBe(
    "application/pdf",
  );
  // Since Chromium 156 the viewer's <embed> lives in a closed user-agent
  // shadow root; the loaded viewer shows up as the PDF extension's frame.
  await expect
    .poll(() =>
      preview
        .frames()
        .some((frame) => frame.url().startsWith(CHROMIUM_PDF_VIEWER_ORIGIN)),
    )
    .toBe(true);
  // The native PDF renderer paints outside the page DOM and has no DOM-ready event.
  await preview.waitForTimeout(1_000);
  expect(preview.isClosed()).toBe(false);
  expect(crashes).toEqual([]);
  return preview;
}

// Server bytes, filenames, inline/attachment headers and every role boundary
// are API proofs in tools/documents/contract.py. The browser proves the
// client side: the Blob download stays byte-identical and Chromium's native
// viewer renders the authenticated top-level PDF (5e442c64).
test("charity admin downloads and opens the Typst PDF byte-identical", async ({
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
    await expectByteIdenticalDownload(row);
    const preview = await expectStableTopLevelPreview(context, row);
    await preview.screenshot({
      path: `${artifactDirectory}/document-pdf-preview.png`,
      fullPage: true,
    });
    await preview.close();
    const accessibility = await analyzeAccessibility(page);
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
