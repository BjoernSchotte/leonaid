import { expect, test } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";

const baseURL = process.env.LEONAID_E2E_BASE_URL;
const proof = process.env.LEONAID_E2E_ARTIFACT_DIR;
const admin = process.env.SURVEY_ADMIN_SESSION;
if (!baseURL || !proof || !admin) throw new Error("Survey fixtures required");
const seed = JSON.parse(
  readFileSync(`${proof}/export-browser-access.json`, "utf8"),
);
const api = `${baseURL}/api/v1/surveys/${seed.surveyId}`;
async function session(browser, token) {
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
  const received = page.waitForResponse(
    (r) => r.url() === `${api}/analysis` && r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Auswertung erstellen", exact: true })
    .click();
  const snapshot = await (await received).json();
  await expect(
    page.locator(`[data-snapshot-id="${snapshot.id}"]`),
  ).toBeVisible();
  return { context, page, snapshot };
}
const labels = {
  responses_csv: "Einzelantworten · CSV",
  responses_xlsx: "Einzelantworten · Excel",
  analysis_xlsx: "Auswertung · Excel",
  analysis_pdf: "Auswertung · PDF",
};
async function exportRow(page, product) {
  const row = page
    .getByRole("region", { name: "Auswertung exportieren", exact: true })
    .getByRole("listitem", { name: labels[product], exact: true });
  const response = page.waitForResponse(
    (r) => r.url() === `${api}/exports` && r.request().method() === "POST",
  );
  await row
    .getByRole("button", { name: "Datei erstellen", exact: true })
    .click();
  const job = await (await response).json();
  await expect(
    row.getByText("Bereit zum Herunterladen", { exact: true }),
  ).toBeVisible({ timeout: 45_000 });
  return { row, job };
}

test("populated snapshot exports match visible metrics and report-only access denies raw jobs", async ({
  browser,
}) => {
  test.setTimeout(120_000);
  const { context, page, snapshot } = await session(browser, admin);
  expect(snapshot.participationCount).toBe(5);
  const format = (value) =>
    new Intl.NumberFormat("de-DE", { maximumFractionDigits: 2 }).format(value);
  for (const q of snapshot.questions) {
    const section = page.locator(`[data-question-id="${q.questionId}"]`);
    for (const [index, key] of [
      "relevant",
      "answered",
      "unanswered",
      "hidden",
      "invalid",
    ].entries()) {
      await expect(
        section
          .locator(".survey-analytics-counts")
          .first()
          .locator("dd")
          .nth(index),
      ).toHaveText(format(q[key]));
    }
    for (const [key, label] of [
      ["mean", "Durchschnitt"],
      ["nps", "Net Promoter Score"],
    ]) {
      if (q[key] !== null)
        await expect(
          section
            .locator(".survey-analytics-metrics > div")
            .filter({ has: page.getByText(label, { exact: true }) })
            .locator("dd"),
        ).toHaveText(format(q[key]));
    }
  }
  // Editing a filter does not change which already-displayed result is exported.
  await page.getByLabel("Teilantworten", { exact: true }).uncheck();
  const jobs = {};
  for (const product of Object.keys(labels)) {
    const { row, job } = await exportRow(page, product);
    expect(job.snapshotId).toBe(snapshot.id);
    jobs[product] = job.id;
    const event = page.waitForEvent("download");
    await row
      .getByRole("button", { name: "Herunterladen", exact: true })
      .click();
    const download = await event;
    expect(await download.failure()).toBeNull();
    const extension = product.endsWith("csv")
      ? "csv"
      : product.endsWith("pdf")
        ? "pdf"
        : "xlsx";
    await download.saveAs(`${proof}/browser-${product}.${extension}`);
  }
  const member = await session(browser, seed.memberToken);
  expect(member.snapshot.participationCount).toBe(5);
  const panel = member.page.getByRole("region", {
    name: "Auswertung exportieren",
    exact: true,
  });
  await expect(panel.getByRole("listitem")).toHaveCount(2);
  for (const product of ["responses_csv", "responses_xlsx"]) {
    await expect(
      panel.getByRole("listitem", { name: labels[product], exact: true }),
    ).toHaveCount(0);
    const denied = await member.context.request.post(`${api}/exports`, {
      data: {
        operationId: `forbidden-${product}`,
        snapshotId: member.snapshot.id,
        product,
      },
    });
    expect(denied.status()).toBe(404);
    const download = await member.context.request.get(
      `${api}/exports/${jobs[product]}/download`,
    );
    expect(download.status()).toBe(404);
    expect(download.headers()["content-disposition"]).toBeUndefined();
  }
  const { row, job } = await exportRow(member.page, "analysis_pdf");
  const event = member.page.waitForEvent("download");
  await row.getByRole("button", { name: "Herunterladen", exact: true }).click();
  expect(await (await event).failure()).toBeNull();
  writeFileSync(
    `${proof}/export-populated-browser.json`,
    JSON.stringify({
      snapshot,
      jobs,
      memberJob: job.id,
      memberSnapshot: member.snapshot.id,
    }),
  );
  await context.close();
  await member.context.close();
});

test("revoked report access blocks existing downloads and trash clears a stale download action", async ({
  browser,
}) => {
  test.setTimeout(120_000);
  const previous = JSON.parse(
    readFileSync(`${proof}/export-populated-browser.json`, "utf8"),
  );
  const member = await session(browser, seed.memberToken);
  await expect(
    member.page.getByRole("region", {
      name: "Auswertung exportieren",
      exact: true,
    }),
  ).toHaveCount(0);
  for (const suffix of ["", "/download"]) {
    const response = await member.context.request.get(
      `${api}/exports/${previous.memberJob}${suffix}`,
    );
    expect(response.status()).toBe(404);
    expect(response.headers()["content-disposition"]).toBeUndefined();
  }
  const retry = await member.context.request.post(`${api}/exports`, {
    data: {
      operationId: "after-revoke",
      product: "analysis_pdf",
      snapshotId: previous.memberSnapshot,
    },
  });
  expect(retry.status()).toBe(404);
  const owner = await session(browser, admin);
  const { row } = await exportRow(owner.page, "analysis_pdf");
  const summary = await (await owner.context.request.get(api)).json();
  const trashed = await owner.context.request.post(`${api}/transition`, {
    data: {
      operationId: "trash-visible-export",
      expectedRevision: summary.revision,
      action: "trash",
    },
  });
  expect(trashed.ok()).toBeTruthy();
  const downloads = [];
  owner.page.on("download", (d) => downloads.push(d));
  const denied = owner.page.waitForResponse(
    (r) => r.url().endsWith("/download") && r.status() === 404,
  );
  await row.getByRole("button", { name: "Herunterladen", exact: true }).click();
  await denied;
  await expect(row.getByRole("alert")).toContainText("nicht mehr zugänglich");
  await expect(
    row.getByRole("button", { name: "Herunterladen", exact: true }),
  ).toHaveCount(0);
  expect(downloads).toHaveLength(0);
  writeFileSync(
    `${proof}/export-browser-permissions-proof.json`,
    JSON.stringify(
      {
        reportOnlyRawCreateAndDownloadDenied: true,
        reportDownloadBeforeRevocation: true,
        aggregateAccessAfterRevocation: true,
        existingReportAfterRevocationDenied: true,
        staleDownloadAfterTrashCleared: true,
      },
      null,
      2,
    ),
  );
  await member.context.close();
  await owner.context.close();
});
