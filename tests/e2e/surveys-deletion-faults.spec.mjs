import { test, expect } from "./csp-guard.mjs";
import { readFileSync, writeFileSync } from "node:fs";
const base = process.env.LEONAID_E2E_BASE_URL;
const proof = process.env.LEONAID_E2E_ARTIFACT_DIR;
async function admin(browser) {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 390, height: 844 },
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: process.env.SURVEY_ADMIN_SESSION,
      url: base,
      secure: true,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  return context;
}
// Runs in its own Playwright call after "trash and restore while a
// respondent is editing" (tools/surveys/infrastructure.sh), which leaves
// the survey in the trash and records the first proof keys.
test("erasure request recovers a lost acknowledgement", async ({ browser }) => {
  const { sid } = JSON.parse(
    readFileSync(`${proof}/recovery-state.json`, "utf8"),
  );
  const member = await admin(browser);
  const page = await member.newPage();
  const respondent = await browser.newContext({ ignoreHTTPSErrors: true });
  await page.goto(`${base}/admin/surveys/${sid}`);
  await expect(page.locator("[data-survey-status]")).toHaveAttribute(
    "data-survey-status",
    "deleted",
  );
  await page
    .getByRole("button", { name: "Endgültig löschen", exact: true })
    .click();
  const confirmation = page.getByRole("group", {
    name: "Endgültige Löschung bestätigen",
  });
  const submit = confirmation.getByRole("button", {
    name: "Löschung jetzt beauftragen",
  });
  await confirmation.getByRole("checkbox").check();
  let committed = 0;
  await page.route(
    `**/api/v1/surveys/${sid}/delete-permanently`,
    async (route) => {
      const response = await route.fetch();
      expect(response.status()).toBe(200);
      expect((await response.json()).status).toBe("pending");
      committed++;
      await route.abort("failed");
    },
  );
  await submit.click();
  await expect(
    page.getByRole("region", { name: "Endgültige Löschung", exact: true }),
  ).toContainText("wurde beauftragt");
  expect(committed).toBe(1);
  await page.reload();
  await expect(
    page.getByRole("region", { name: "Endgültige Löschung", exact: true }),
  ).toContainText("wurde beauftragt");
  await expect(
    page.getByRole("button", { name: "Wiederherstellen", exact: true }),
  ).toHaveCount(0);
  const status = await member.request.get(
    `${base}/api/v1/surveys/${sid}/deletion`,
  );
  expect(status.headers()["cache-control"]).toBe("no-store");
  expect(Object.keys(await status.json()).sort()).toEqual([
    "completedAt",
    "requestedAt",
    "retryEventId",
    "status",
    "surveyId",
  ]);
  expect(
    (
      await respondent.request.get(`${base}/api/v1/surveys/${sid}/deletion`)
    ).status(),
  ).toBe(401);
  const result = JSON.parse(
    readFileSync(`${proof}/deletion-ui-proof.json`, "utf8"),
  );
  writeFileSync(
    `${proof}/deletion-ui-proof.json`,
    JSON.stringify({
      ...result,
      lostAcknowledgementRecovered: true,
      pendingStatusSurvivesReload: true,
      contentFreeStatus: true,
      anonymousStatusDenied: true,
    }),
  );
  await member.close();
  await respondent.close();
});
