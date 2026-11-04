import { expect, test } from "./csp-guard.mjs";
import { readFileSync, writeFileSync } from "node:fs";
import { randomUUID } from "node:crypto";

const baseURL = process.env.LEONAID_E2E_BASE_URL;
const token = process.env.SURVEY_ADMIN_SESSION;
const proof = process.env.LEONAID_E2E_ARTIFACT_DIR;
if (!baseURL || !token || !proof)
  throw new Error("Survey fixture access is required");

test("export request retries a lost acknowledgement with the same operation", async ({
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
      title: "Synthetic browser export lost acknowledgement",
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
  const row = panel.getByRole("listitem", {
    name: "Auswertung · Excel",
    exact: true,
  });
  await row
    .getByRole("button", { name: "Datei erstellen", exact: true })
    .click();
  await expect(row.getByRole("alert")).toBeVisible();
  await row
    .getByRole("button", { name: "Anfrage erneut senden", exact: true })
    .click();
  await expect(
    row.getByText("Bereit zum Herunterladen", { exact: true }),
  ).toBeVisible({ timeout: 45_000 });
  const downloadEvent = page.waitForEvent("download");
  await row.getByRole("button", { name: "Herunterladen", exact: true }).click();
  const download = await downloadEvent;
  expect(await download.failure()).toBeNull();
  const content = readFileSync(await download.path());
  expect(content.length).toBeGreaterThan(100);
  expect(content.subarray(0, 2).toString()).toBe("PK");
  expect(requests).toHaveLength(2);
  expect(requests[0]).toEqual(requests[1]);
  expect(requests.every((r) => r.snapshotId === snapshot.id)).toBe(true);
  writeFileSync(
    `${proof}/survey-export-browser-faults.json`,
    JSON.stringify(
      { sameOperationAfterLostAcknowledgement: true, product: "analysis_xlsx" },
      null,
      2,
    ),
  );
  await context.close();
});
