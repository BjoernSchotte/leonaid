import { expect, test } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
import { randomUUID } from "node:crypto";

const baseURL = process.env.LEONAID_E2E_BASE_URL;
const token = process.env.SURVEY_ADMIN_SESSION;
const proof = process.env.LEONAID_E2E_ARTIFACT_DIR;
if (!baseURL || !token || !proof)
  throw new Error("Survey fixture access is required");

test("export UI downloads all four empty-snapshot products and retries a lost acknowledgement", async ({
  browser,
}) => {
  test.setTimeout(120_000);
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1280, height: 900 },
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: token,
      url: baseURL,
      secure: true,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  const sid = randomUUID();
  const api = `${baseURL}/api/v1/surveys/${sid}`;
  const definition = JSON.parse(
    readFileSync("tests/fixtures/surveys/analysis-golden.json", "utf8"),
  ).definition;
  const created = await context.request.post(api, {
    data: {
      operationId: "create",
      title: "Synthetic browser export",
      definition,
    },
  });
  expect(created.ok()).toBeTruthy();
  const published = await context.request.post(`${api}/publish`, {
    data: { operationId: "publish", expectedRevision: 1 },
  });
  expect(published.ok()).toBeTruthy();
  const page = await context.newPage();
  await page.goto(`${baseURL}/admin/surveys/${sid}`);
  await page.getByText("Antworten auswerten", { exact: true }).click();
  const snapshotResponse = page.waitForResponse(
    (r) => r.url() === `${api}/analysis` && r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Auswertung erstellen", exact: true })
    .click();
  const snapshot = await (await snapshotResponse).json();
  expect(snapshot.participationCount).toBe(0);
  const panel = page.getByRole("region", {
    name: "Auswertung exportieren",
    exact: true,
  });
  await expect(panel).toBeVisible();
  const labels = {
    analysis_xlsx: "Auswertung · Excel",
    analysis_pdf: "Auswertung · PDF",
    responses_csv: "Einzelantworten · CSV",
    responses_xlsx: "Einzelantworten · Excel",
  };
  const requests = [];
  let dropped = false;
  await page.route(`${api}/exports`, async (route) => {
    const body = route.request().postDataJSON();
    requests.push(body);
    if (!dropped) {
      dropped = true;
      const committed = await route.fetch();
      expect(committed.ok()).toBeTruthy();
      await route.abort("failed");
    } else await route.continue();
  });
  const downloads = [];
  for (const [product, label] of Object.entries(labels)) {
    const row = panel.getByRole("listitem", { name: label, exact: true });
    await row
      .getByRole("button", { name: "Datei erstellen", exact: true })
      .click();
    if (product === "analysis_xlsx") {
      await expect(row.getByRole("alert")).toBeVisible();
      await row
        .getByRole("button", { name: "Anfrage erneut senden", exact: true })
        .click();
    }
    await expect(
      row.getByText("Bereit zum Herunterladen", { exact: true }),
    ).toBeVisible({ timeout: 45_000 });
    const downloadEvent = page.waitForEvent("download");
    await row
      .getByRole("button", { name: "Herunterladen", exact: true })
      .click();
    const download = await downloadEvent;
    expect(await download.failure()).toBeNull();
    const content = readFileSync(await download.path());
    expect(content.length).toBeGreaterThan(100);
    if (product.endsWith("xlsx"))
      expect(content.subarray(0, 2).toString()).toBe("PK");
    if (product.endsWith("pdf"))
      expect(content.subarray(0, 5).toString()).toBe("%PDF-");
    if (product.endsWith("csv")) {
      expect(content.toString()).toContain(snapshot.id);
      expect(content.toString()).toContain("metadata");
    }
    downloads.push({
      product,
      filename: download.suggestedFilename(),
      bytes: content.length,
    });
  }
  expect(requests).toHaveLength(5);
  expect(requests[0]).toEqual(requests[1]);
  expect(requests.every((r) => r.snapshotId === snapshot.id)).toBe(true);
  await page.setViewportSize({ width: 390, height: 844 });
  await panel.scrollIntoViewIfNeeded();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await panel.screenshot({ path: `${proof}/surveys-exports-mobile.png` });
  writeFileSync(
    `${proof}/survey-export-browser.json`,
    JSON.stringify(
      {
        downloads,
        sameOperationAfterLostAcknowledgement: true,
        sameSnapshotForAllProducts: true,
        fixture: "empty snapshot",
        mobileWidth: 390,
      },
      null,
      2,
    ),
  );
  await context.close();
});
