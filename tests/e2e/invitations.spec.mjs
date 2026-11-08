import { expect, test } from "./csp-guard.mjs";

// Browser parts of invitations and email changes: the public code entry on
// mobile and the confirmation page, which drops its token from the URL.
// Scope, history, reissue, correction and atomic confirmation are proven by
// tools/invitations/contract.py against the same stack.
const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const uiEmailConfirmToken = process.env.UI_EMAIL_CONFIRM_TOKEN;

if (!baseUrl || !artifactDirectory || !uiEmailConfirmToken) {
  throw new Error("POC-041 browser environment is incomplete");
}

test("public code entry is usable on mobile", async ({ browser }) => {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();
  try {
    await page.goto(`${baseUrl}/invite`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "Einladung annehmen",
    );
    await expect(page.locator("#accept-email")).toBeVisible();
    await expect(page.locator("#accept-code")).toHaveAttribute(
      "autocomplete",
      "one-time-code",
    );
    await expect(page.locator('[data-testid="accept-submit"]')).toBeVisible();
    await page.screenshot({
      path: `${artifactDirectory}/invitation-code-mobile.png`,
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});

test("new login email is confirmed publicly", async ({ browser }) => {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();
  try {
    await page.goto(
      `${baseUrl}/email-change?token=${encodeURIComponent(uiEmailConfirmToken)}`,
    );
    await expect(page).toHaveURL(`${baseUrl}/email-change`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "Neue Login-E-Mail bestätigen",
    );
    await page.getByTestId("email-change-submit").click();
    await expect(page.locator("#email-change-status")).toContainText(
      "Neue Login-E-Mail bestätigt",
    );
    await expect(
      page.getByRole("link", { name: "Mit neuer E-Mail anmelden" }),
    ).toBeVisible();
    await page.screenshot({
      path: `${artifactDirectory}/email-change-confirm-mobile.png`,
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});
