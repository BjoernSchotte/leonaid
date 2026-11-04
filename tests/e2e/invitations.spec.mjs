import { expect, test } from "./csp-guard.mjs";
import {
  memberPane,
  openInviteDialog,
  openMember,
  toast,
} from "./member-list.mjs";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const klaraSession = process.env.KLARA_SESSION;
const systemSession = process.env.SYSTEM_SESSION;
const uiResendInvitationId = process.env.UI_RESEND_INVITATION_ID;
const uiCorrectInvitationId = process.env.UI_CORRECT_INVITATION_ID;
const uiRevokeInvitationId = process.env.UI_REVOKE_INVITATION_ID;
const uiEmailConfirmToken = process.env.UI_EMAIL_CONFIRM_TOKEN;

if (
  !baseUrl ||
  !artifactDirectory ||
  !klaraSession ||
  !systemSession ||
  !uiResendInvitationId ||
  !uiCorrectInvitationId ||
  !uiRevokeInvitationId ||
  !uiEmailConfirmToken
) {
  throw new Error("POC-041 browser environment is incomplete");
}

async function sessionPage(browser, token) {
  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    ignoreHTTPSErrors: true,
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: token,
      url: baseUrl,
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
    },
  ]);
  const page = await context.newPage();
  await page.goto(`${baseUrl}/admin/members`);
  await expect(page.locator('[data-testid="display-name"]')).toBeVisible();
  return { context, page };
}

async function invitationsPage(browser, token) {
  const session = await sessionPage(browser, token);
  await session.page.getByTestId("member-section-invitations").click();
  await session.page.waitForURL(`${baseUrl}/admin/members/invitations`);
  await expect(
    session.page.getByRole("heading", { level: 1, name: "Einladungen" }),
  ).toBeVisible();
  return session;
}

test("charity admin can select only an action they manage", async ({
  browser,
}) => {
  const { context, page } = await sessionPage(browser, klaraSession);
  try {
    const dialog = await openInviteDialog(page);
    const action = dialog.getByTestId("invite-action");
    await expect(
      page.locator('[data-nav-key="members"][aria-current="page"]').first(),
    ).toBeVisible();
    await expect(action.locator("option")).toHaveCount(1);
    await expect(action).toContainText("Krapfentaxi 2026");
    await expect(action).not.toContainText("Krapfentaxi Nord 2026");
    await expect(
      dialog.getByTestId("invite-role").locator("option"),
    ).toHaveCount(4);

    const direct = await context.request.post(`${baseUrl}/api/v1/invitations`, {
      data: {
        actionId: "20000000-0000-4000-8000-000000000003",
        displayName: "Direkter Fremdzugriff",
        email: "foreign-action@leonaid.invalid",
        role: "acquirer",
      },
    });
    expect(direct.status()).toBe(403);
    expect((await direct.json()).error.code).toBe(
      "invitation_action_forbidden",
    );

    await page.screenshot({
      path: `${artifactDirectory}/invitation-charity-admin.png`,
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});

test("system admin gets the globally invitable actions", async ({
  browser,
}) => {
  const { context, page } = await sessionPage(browser, systemSession);
  try {
    const dialog = await openInviteDialog(page);
    const action = dialog.getByTestId("invite-action");
    await expect(action.locator("option")).toHaveCount(2);
    await expect(action).toContainText("Krapfentaxi 2026");
    await expect(action).toContainText("Krapfentaxi Nord 2026");
    await expect(action).not.toContainText("Krapfentaxi 2025");
  } finally {
    await context.close();
  }
});

test("charity admin manages the full invitation history", async ({
  browser,
}) => {
  const { context, page } = await invitationsPage(browser, klaraSession);
  try {
    await expect(
      page.locator('[data-nav-key="members"][aria-current="page"]').first(),
    ).toBeVisible();
    await expect(page.getByText("Foreign Lifecycle Pilot")).toHaveCount(0);
    await expect(page.locator(".invitation-row")).not.toHaveCount(0);

    const resendRow = page.getByTestId(`invitation-${uiResendInvitationId}`);
    await resendRow.getByTestId("invitation-resend").click();
    await expect(
      toast(page, "Eine neue Einladung wurde versendet"),
    ).toBeVisible();
    await expect(resendRow).toHaveAttribute("data-status", "revoked");

    const correctRow = page.getByTestId(`invitation-${uiCorrectInvitationId}`);
    await correctRow.getByTestId("invitation-correct-address").click();
    const correction = page.getByRole("dialog", {
      name: "Adresse korrigieren",
    });
    const correctedEmail = "ui-corrected-pilot@leonaid.invalid";
    await correction.getByLabel("Neue Login-E-Mail").fill(correctedEmail);
    await correction
      .getByRole("button", { name: "Korrigieren & senden" })
      .click();
    await expect(correction).toBeHidden();
    await expect(toast(page, "korrigierte Adresse")).toBeVisible();
    await expect(
      page.locator(".invitation-row", { hasText: correctedEmail }),
    ).toBeVisible();
    await expect(correctRow).toHaveAttribute("data-status", "revoked");

    const revokeRow = page.getByTestId(`invitation-${uiRevokeInvitationId}`);
    await revokeRow.getByTestId("invitation-revoke").click();
    const confirmation = page.getByRole("alertdialog");
    await expect(confirmation).toContainText("Einladung wirklich widerrufen?");
    await confirmation
      .getByRole("button", { name: "Jetzt widerrufen" })
      .click();
    await expect(toast(page, "wurde widerrufen")).toBeVisible();
    await expect(revokeRow).toHaveAttribute("data-status", "revoked");

    await page.getByTestId("invitation-status-filter").selectOption("accepted");
    await expect(page.locator(".invitation-row")).not.toHaveCount(0);
    await expect(
      page.locator('.invitation-row:not([data-status="accepted"])'),
    ).toHaveCount(0);

    await page.screenshot({
      path: `${artifactDirectory}/invitation-lifecycle-admin.png`,
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});

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

test("system admin requests an email correction clearly", async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 1280, height: 1000 },
    ignoreHTTPSErrors: true,
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: systemSession,
      url: baseUrl,
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
    },
  ]);
  const page = await context.newPage();
  try {
    await page.goto(`${baseUrl}/admin/members`);
    const pane = await openMember(page, "E-Mail Korrektur UI");
    await pane.getByTestId("member-email-change-open").click();
    const dialog = page.getByRole("dialog", { name: "Anmeldeadresse ändern" });
    await dialog
      .getByTestId("member-email-change-input")
      .fill("ui-email-start-new@leonaid.invalid");
    await dialog.getByTestId("member-email-change-submit").click();
    await expect(dialog).toBeHidden();
    await expect(
      memberPane(page).getByTestId("member-email-change-success"),
    ).toContainText("wartet auf Bestätigung");
    await page.screenshot({
      path: `${artifactDirectory}/email-change-admin.png`,
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
