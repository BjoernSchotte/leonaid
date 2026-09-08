import { test, expect } from "@playwright/test";
import { readFileSync, writeFileSync, renameSync } from "node:fs";

const baseURL = process.env.LEONAID_E2E_BASE_URL;
const proof = process.env.LEONAID_E2E_ARTIFACT_DIR;
const token = process.env.SURVEY_ADMIN_SESSION;
const seed = JSON.parse(
  readFileSync(`${proof}/export-browser-access.json`, "utf8"),
);
function signal(name, value) {
  const path = `${proof}/export-state-${name}.json`;
  writeFileSync(`${path}.tmp`, JSON.stringify(value));
  renameSync(`${path}.tmp`, path);
}

test("real failed export offers a fresh job after retry and status connection recovery", async ({
  browser,
}) => {
  test.setTimeout(150_000);
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
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
  const page = await context.newPage();
  await page.goto(`${baseURL}/admin/surveys/${seed.surveyId}`);
  await page.getByText("Antworten auswerten", { exact: true }).click();
  await page
    .getByRole("button", { name: "Auswertung erstellen", exact: true })
    .click();
  const row = page.getByRole("listitem", {
    name: "Auswertung · PDF",
    exact: true,
  });
  const created = page.waitForResponse(
    (r) => r.url().endsWith("/exports") && r.request().method() === "POST",
  );
  await row
    .getByRole("button", { name: "Datei erstellen", exact: true })
    .click();
  const firstResponse = await created;
  const first = await firstResponse.json();
  expect(first.status).toBe("queued");
  await expect(row.getByRole("status")).toHaveText("Export wartet");
  await page.route(`**/exports/${first.id}`, (route) => route.abort("failed"), {
    times: 1,
  });
  signal("queued", first);
  await expect(row.getByRole("alert")).toBeVisible();
  await expect(
    row.getByRole("button", { name: "Herunterladen", exact: true }),
  ).toHaveCount(0);
  await row
    .getByRole("button", { name: "Status erneut laden", exact: true })
    .click();
  await expect(row.getByRole("status")).toHaveText(
    "Erstellung wird automatisch erneut versucht",
    { timeout: 45_000 },
  );
  signal("retry-visible", {});
  await expect(row.getByRole("status")).toHaveText(
    "Datei konnte nicht erstellt werden",
    { timeout: 45_000 },
  );
  await expect(
    row.getByRole("button", { name: "Herunterladen", exact: true }),
  ).toHaveCount(0);
  await page.screenshot({
    path: `${proof}/export-state-failed.png`,
    fullPage: true,
  });
  const replaced = page.waitForResponse(
    (r) => r.url().endsWith("/exports") && r.request().method() === "POST",
  );
  await row
    .getByRole("button", { name: "Datei erstellen", exact: true })
    .click();
  const secondResponse = await replaced;
  const second = await secondResponse.json();
  expect(second.id).not.toBe(first.id);
  expect(second.snapshotId).toBe(first.snapshotId);
  expect(secondResponse.request().postDataJSON().operationId).not.toBe(
    firstResponse.request().postDataJSON().operationId,
  );
  signal("replacement", second);
  await expect(row.getByRole("status")).toHaveText("Bereit zum Herunterladen", {
    timeout: 45_000,
  });
  const downloaded = page.waitForEvent("download");
  await row.getByRole("button", { name: "Herunterladen", exact: true }).click();
  const download = await downloaded;
  expect(await download.failure()).toBeNull();
  expect(
    readFileSync(await download.path())
      .subarray(0, 5)
      .toString(),
  ).toBe("%PDF-");
  signal("browser-proof", {
    queuedObserved: true,
    statusNetworkFailureRecovered: true,
    retryObserved: true,
    terminalFailureObserved: true,
    noFalseDownload: true,
    replacementHasNewOperation: true,
    sameSnapshotRetained: true,
    actualPdfDownloaded: true,
  });
  await context.close();
});
