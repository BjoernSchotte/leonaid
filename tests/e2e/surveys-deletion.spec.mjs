import { test, expect } from "@playwright/test";
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
test("trash and request erasure while a respondent is editing", async ({
  browser,
}) => {
  const { sid, job } = JSON.parse(
    readFileSync(`${proof}/recovery-state.json`, "utf8"),
  );
  const member = await admin(browser);
  const page = await member.newPage();
  const respondent = await browser.newContext({ ignoreHTTPSErrors: true });
  const publicPage = await respondent.newPage();
  await page.goto(`${base}/admin/surveys/${sid}`);
  await publicPage.goto(`${base}/surveys/${sid}`);
  await publicPage.getByRole("button", { name: "Umfrage beginnen" }).click();
  const input = publicPage.locator("[data-name=answer] input");
  await input.fill("Accepted before trash");
  await expect(publicPage.locator("[data-save-state]")).toHaveAttribute(
    "data-save-state",
    "saved",
  );
  await page
    .getByRole("button", { name: "In Papierkorb verschieben", exact: true })
    .click();
  await page
    .getByRole("button", {
      name: "Jetzt in Papierkorb verschieben",
      exact: true,
    })
    .click();
  await expect(page.locator("[data-survey-status]")).toHaveAttribute(
    "data-survey-status",
    "deleted",
  );
  await input.fill("Must not save after trash");
  await expect(publicPage.locator("[data-save-state]")).toHaveAttribute(
    "data-save-state",
    "error",
  );
  await expect(
    publicPage.getByText("Diese Umfrage nimmt keine Antworten mehr an.", {
      exact: true,
    }),
  ).toBeVisible();
  expect(
    (
      await member.request.get(
        `${base}/api/v1/surveys/${sid}/exports/${job}/download`,
      )
    ).status(),
  ).toBe(404);
  const summary = await (
    await member.request.get(`${base}/api/v1/surveys/${sid}`)
  ).json();
  expect(
    (
      await member.request.post(`${base}/api/v1/surveys/${sid}/invitations`, {
        data: {
          operationId: "after-trash",
          expectedRevision: summary.revision,
          recipientEmail: "deleted@example.com",
          expiresInDays: 30,
        },
      })
    ).status(),
  ).toBe(409);
  // A separate invitation-mode fixture provides a successful pre-trash baseline;
  // the anonymous survey above would reject invitations even while active.
  const invitationSurvey = crypto.randomUUID();
  const invitationBase = `${base}/api/v1/surveys/${invitationSurvey}`;
  expect(
    (
      await member.request.post(invitationBase, {
        data: {
          operationId: "create",
          title: "Synthetic invited deletion",
          definition: {
            pages: [
              { name: "main", elements: [{ name: "answer", type: "text" }] },
            ],
          },
        },
      })
    ).status(),
  ).toBe(200);
  expect(
    (
      await member.request.put(`${invitationBase}/access`, {
        data: {
          operationId: "access",
          expectedRevision: 1,
          accessMode: "invitation",
        },
      })
    ).status(),
  ).toBe(200);
  const invitationDraft = await (
    await member.request.get(`${invitationBase}/draft`)
  ).json();
  expect(
    (
      await member.request.post(`${invitationBase}/publish`, {
        data: {
          operationId: "publish",
          expectedRevision: invitationDraft.revision,
        },
      })
    ).status(),
  ).toBe(200);
  const activeInvitation = await (
    await member.request.get(invitationBase)
  ).json();
  const invitationInput = {
    operationId: "before-trash",
    expectedRevision: activeInvitation.revision,
    recipientEmail: "baseline@example.com",
    expiresInDays: 30,
  };
  expect(
    (
      await member.request.post(`${invitationBase}/invitations`, {
        data: invitationInput,
      })
    ).status(),
  ).toBe(200);
  const trashedInvitation = await member.request.post(
    `${invitationBase}/transition`,
    {
      data: {
        operationId: "trash",
        expectedRevision: activeInvitation.revision,
        action: "trash",
      },
    },
  );
  expect(trashedInvitation.status()).toBe(200);
  expect(
    (
      await member.request.post(`${invitationBase}/invitations`, {
        data: {
          ...invitationInput,
          operationId: "after-trash",
          expectedRevision: (await trashedInvitation.json()).revision,
        },
      })
    ).status(),
  ).toBe(409);
  await page
    .getByRole("button", { name: "Wiederherstellen", exact: true })
    .click();
  await expect(page.locator("[data-survey-status]")).toHaveAttribute(
    "data-survey-status",
    "ended",
  );
  expect(
    (await member.request.get(`${base}/api/v1/public/surveys/${sid}`)).status(),
  ).toBe(409);
  await publicPage.reload();
  await expect(
    publicPage.getByRole("button", { name: "Umfrage beginnen" }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "In Papierkorb verschieben", exact: true })
    .click();
  await page
    .getByRole("button", {
      name: "Jetzt in Papierkorb verschieben",
      exact: true,
    })
    .click();
  await page
    .getByRole("button", { name: "Endgültig löschen", exact: true })
    .click();
  const confirmation = page.getByRole("group", {
    name: "Endgültige Löschung bestätigen",
  });
  const submit = confirmation.getByRole("button", {
    name: "Löschung jetzt beauftragen",
  });
  await expect(submit).toBeDisabled();
  await confirmation.getByRole("checkbox").check();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: `${proof}/deletion-confirm-mobile.png`,
    fullPage: true,
  });
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
  writeFileSync(
    `${proof}/deletion-ui-proof.json`,
    JSON.stringify({
      openRespondentSaveRejected: true,
      trashBlocksDownloadAndInvitationCreation: true,
      restoreRemainsClosed: true,
      explicitConsentRequired: true,
      lostAcknowledgementRecovered: true,
      pendingStatusSurvivesReload: true,
      contentFreeStatus: true,
      anonymousStatusDenied: true,
    }),
  );
  await member.close();
  await respondent.close();
});
test("failed deletion can be retried by the administrator", async ({
  browser,
}) => {
  const { sid } = JSON.parse(
    readFileSync(`${proof}/recovery-state.json`, "utf8"),
  );
  const context = await admin(browser);
  const page = await context.newPage();
  await page.goto(`${base}/admin/surveys/${sid}`);
  await expect(
    page.getByRole("region", { name: "Endgültige Löschung", exact: true }),
  ).toContainText("konnte nicht abgeschlossen werden");
  await page
    .getByRole("button", { name: "Löschung erneut versuchen", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Endgültige Löschung", exact: true }),
  ).toContainText("bearbeitet den Auftrag weiter");
  await expect(
    page.getByRole("button", {
      name: "Löschung erneut versuchen",
      exact: true,
    }),
  ).toHaveCount(0);
  const result = JSON.parse(
    readFileSync(`${proof}/deletion-ui-proof.json`, "utf8"),
  );
  result.adminRetriesPersistedFailureThroughExistingJobApi = true;
  writeFileSync(
    `${proof}/deletion-ui-proof.json`,
    JSON.stringify(result, null, 2) + "\n",
  );
  await context.close();
});
test("completed erasure is visible after the production worker runs", async ({
  browser,
}) => {
  const { sid } = JSON.parse(
    readFileSync(`${proof}/recovery-state.json`, "utf8"),
  );
  const context = await admin(browser);
  const page = await context.newPage();
  await page.goto(`${base}/admin/surveys/${sid}`);
  await expect(
    page.getByRole("region", { name: "Endgültige Löschung", exact: true }),
  ).toContainText("wurde endgültig gelöscht", { timeout: 60000 });
  await page.reload();
  await expect(
    page.getByRole("region", { name: "Endgültige Löschung", exact: true }),
  ).toContainText("wurde endgültig gelöscht");
  expect(
    (await context.request.get(`${base}/api/v1/surveys/${sid}`)).status(),
  ).toBe(404);
  await page.screenshot({
    path: `${proof}/deletion-completed-mobile.png`,
    fullPage: true,
  });
  const result = JSON.parse(
    readFileSync(`${proof}/deletion-ui-proof.json`, "utf8"),
  );
  result.productionWorkerCompletionAndReload = true;
  writeFileSync(
    `${proof}/deletion-ui-proof.json`,
    JSON.stringify(result, null, 2) + "\n",
  );
  await context.close();
});
