import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

const baseURL = process.env.LEONAID_E2E_BASE_URL;
const token = process.env.SURVEY_ADMIN_SESSION;
const proof = process.env.LEONAID_E2E_ARTIFACT_DIR;
if (!baseURL || !token || !proof)
  throw new Error("Survey fixture access is required");
const frozen = JSON.parse(
  readFileSync(`${proof}/survey-analysis-snapshot.json`, "utf8"),
);

test("analysis filters, immutable results, chart/table agreement and lost acknowledgement", async ({
  browser,
}) => {
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
  const page = await context.newPage();
  await page.goto(`${baseURL}/admin/surveys/${frozen.surveyId}`);
  await page.getByText("Antworten auswerten", { exact: true }).click();
  const filters = page.getByRole("region", {
    name: "Auswertung erstellen",
    exact: true,
  });
  const result = page.getByRole("region", { name: "Ergebnisse", exact: true });
  await expect(filters.getByLabel("Fragebogen-Version")).toHaveValue(/.+/);
  await filters
    .getByLabel("Fragebogen-Version")
    .selectOption(frozen.filter.versionId);
  const format = (value) =>
    new Intl.NumberFormat("de-DE", { maximumFractionDigits: 2 }).format(value);
  async function analyze() {
    const response = page.waitForResponse(
      (r) =>
        r.url().endsWith(`/surveys/${frozen.surveyId}/analysis`) &&
        r.request().method() === "POST",
    );
    await filters
      .getByRole("button", { name: "Auswertung erstellen", exact: true })
      .click();
    const received = await response;
    expect(received.status()).toBe(200);
    const snapshot = await received.json();
    await expect(result).toHaveAttribute("data-snapshot-id", snapshot.id);
    await expect(
      result.getByText(
        `Ausgewählte Teilnahmen: ${snapshot.participationCount}`,
        { exact: true },
      ),
    ).toBeVisible();
    const overview = result.getByRole("region", {
      name: "Teilnahmen dieser Version, dieses Zeitraums und dieser Antwortquelle vor dem Statusfilter",
    });
    for (const [index, key] of [
      "in_progress",
      "partial",
      "completed",
    ].entries()) {
      await expect(overview.locator("dd").nth(index)).toHaveText(
        format(snapshot.statusCounts[key]),
      );
    }
    for (const q of snapshot.questions) {
      const section = result.locator(`[data-question-id="${q.questionId}"]`);
      const distributions = [
        ...(q.counts.length ? [q.counts] : []),
        ...q.matrixRows.map((row) => row.counts),
      ];
      for (const [distributionIndex, counts] of distributions.entries()) {
        const chart = section
          .locator(".survey-analytics-bars")
          .nth(distributionIndex);
        const details = section
          .locator(".survey-analytics-table")
          .nth(distributionIndex);
        if (!(await details.getAttribute("open"))) {
          // Presence, rather than the empty string value, controls native details.
          if (!(await details.evaluate((element) => element.open)))
            await details.locator("summary").click();
        }
        await expect(details.getByRole("table")).toBeVisible();
        for (const [index, bucket] of counts.entries()) {
          const share =
            bucket.percentage === null
              ? "Keine gültigen Antworten"
              : `${format(bucket.percentage)} %`;
          await expect(
            chart.locator(".survey-analytics-bar").nth(index),
          ).toContainText(
            `${format(bucket.count)} · ${bucket.percentage === null ? "—" : share}`,
          );
          const cells = details
            .locator("tbody tr")
            .nth(index)
            .getByRole("cell");
          await expect(cells.nth(0)).toHaveText(format(bucket.count));
          await expect(cells.nth(1)).toHaveText(share);
        }
        await details.locator("summary").click();
      }
    }
    return snapshot;
  }
  const initial = await analyze();
  expect(initial.versionNumber).toBe(1);
  expect(initial.filter.statuses).toEqual(["partial", "completed"]);
  expect(initial.filter.isTest).toBe(false);
  const oldId = initial.id;
  // Editing filters leaves the applied result accurately labelled until submitted.
  await filters.getByLabel("Teilantworten", { exact: true }).uncheck();
  await expect(result).toHaveAttribute("data-snapshot-id", oldId);
  const complete = await analyze();
  expect(complete.participationCount).toBe(1);
  expect(complete.questions.find((q) => q.questionId === "nps").nps).toBe(100);
  const nps = result.locator('[data-question-id="nps"]');
  const summary = nps.locator("summary");
  await summary.focus();
  await page.keyboard.press("Enter");
  await expect(nps.getByRole("table")).toBeVisible();
  for (const [index, bucket] of complete.questions
    .find((q) => q.questionId === "nps")
    .counts.entries()) {
    const row = nps.locator("tbody tr").nth(index);
    await expect(row.getByRole("cell").nth(0)).toHaveText(format(bucket.count));
    await expect(row.getByRole("cell").nth(1)).toHaveText(
      `${format(bucket.percentage)} %`,
    );
  }
  await page.screenshot({
    path: `${proof}/surveys-analytics-desktop.png`,
    fullPage: true,
  });
  await nps.screenshot({ path: `${proof}/surveys-analytics-chart.png`, style: ".ui-topbar { position: static !important; }" });
  await filters
    .getByLabel("Fragebogen-Version")
    .selectOption({ label: "Version 2" });
  const second = await analyze();
  expect(second.participationCount).toBe(1);
  expect(second.questions.find((q) => q.questionId === "nps").nps).toBe(-100);
  await filters.getByLabel("Teilnahme begonnen ab").fill("2099-01-01T00:00");
  const empty = await analyze();
  expect(empty.participationCount).toBe(0);
  await expect(
    result.getByText(/Für diese Filter gibt es keine Teilnahmen/),
  ).toBeVisible();
  await expect(result).toContainText("Keine gültigen Antworten");
  await expect(result).not.toContainText("NaN");
  await filters.getByLabel("Teilnahme begonnen ab").fill("");
  await filters
    .getByLabel("Fragebogen-Version")
    .selectOption(frozen.filter.versionId);
  await filters.getByLabel("Teilantworten", { exact: true }).check();
  await filters.getByLabel("In Bearbeitung", { exact: true }).check();
  const all = await analyze();
  expect(all.participationCount).toBe(6);
  expect(all.questions.find((q) => q.questionId === "nps").nps).toBe(-50);
  // Forward a real successful write, then lose its HTTP acknowledgement.
  let requestBody;
  let committed;
  await page.route(
    `**/surveys/${frozen.surveyId}/analysis`,
    async (route) => {
      requestBody = route.request().postDataJSON();
      const response = await route.fetch();
      expect(response.status()).toBe(200);
      committed = await response.json();
      await route.abort("failed");
    },
    { times: 1 },
  );
  await filters
    .getByRole("button", { name: "Auswertung erstellen", exact: true })
    .click();
  await expect(
    filters.getByRole("button", { name: "Auswertung erneut anfordern" }),
  ).toBeVisible();
  const repeat = page.waitForRequest(
    (r) =>
      r.url().endsWith(`/surveys/${frozen.surveyId}/analysis`) &&
      r.method() === "POST",
  );
  await filters
    .getByRole("button", { name: "Auswertung erneut anfordern" })
    .click();
  expect((await repeat).postDataJSON()).toEqual(requestBody);
  await expect(result).toHaveAttribute("data-snapshot-id", committed.id);
  await page.setViewportSize({ width: 390, height: 844 });
  await result.locator('[data-question-id="multi"] summary').click();
  await expect(
    result.locator('[data-question-id="multi"]').getByRole("table"),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: `${proof}/surveys-analytics-mobile.png`,
    fullPage: true,
  });
  await result
    .locator('[data-question-id="multi"]')
    .screenshot({ path: `${proof}/surveys-analytics-mobile-chart.png` });
  const read = await context.request.get(
    `${baseURL}/api/v1/surveys/${frozen.surveyId}/analysis/${oldId}`,
  );
  expect(await read.json()).toEqual(initial);
  await context.close();
});
