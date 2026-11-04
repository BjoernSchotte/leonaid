import { expect, test } from "./csp-guard.mjs";
import { readFileSync } from "node:fs";

const baseURL = process.env.LEONAID_E2E_BASE_URL;
const token = process.env.SURVEY_ADMIN_SESSION;
const proof = process.env.LEONAID_E2E_ARTIFACT_DIR;
if (!baseURL || !token || !proof)
  throw new Error("Survey fixture access is required");
const frozen = JSON.parse(
  readFileSync(`${proof}/survey-analysis-snapshot.json`, "utf8"),
);

test("analysis request retries a lost acknowledgement with the same filter", async ({
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
  await filters.getByLabel("Teilantworten", { exact: true }).check();
  await filters.getByLabel("In Bearbeitung", { exact: true }).check();
  // Same precondition as in surveys-analytics.spec.mjs: a result for these
  // filters is shown when the next request loses its acknowledgement.
  const shown = page.waitForResponse(
    (r) =>
      r.url().endsWith(`/surveys/${frozen.surveyId}/analysis`) &&
      r.request().method() === "POST",
  );
  await filters
    .getByRole("button", { name: "Auswertung erstellen", exact: true })
    .click();
  const all = await (await shown).json();
  expect(all.participationCount).toBe(6);
  await expect(result).toHaveAttribute("data-snapshot-id", all.id);
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
  await context.close();
});
