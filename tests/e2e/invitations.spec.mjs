import { expect, test } from "@playwright/test";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const klaraSession = process.env.KLARA_SESSION;
const systemSession = process.env.SYSTEM_SESSION;
const uiResendInvitationId = process.env.UI_RESEND_INVITATION_ID;
const uiCorrectInvitationId = process.env.UI_CORRECT_INVITATION_ID;
const uiRevokeInvitationId = process.env.UI_REVOKE_INVITATION_ID;

if (
  !baseUrl ||
  !artifactDirectory ||
  !klaraSession ||
  !systemSession ||
  !uiResendInvitationId ||
  !uiCorrectInvitationId ||
  !uiRevokeInvitationId
) {
  throw new Error("POC-041 Browserumgebung ist unvollständig");
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
  await page.getByRole("tab", { name: /Mitglied einladen/ }).click();
  await expect(page.locator('[data-testid="invite-action"]')).toBeEnabled();
  return { context, page };
}

test("Charity-Admin kann nur eine selbst verwaltete Aktion auswählen", async ({
  browser,
}) => {
  const { context, page } = await sessionPage(browser, klaraSession);
  try {
    const action = page.locator('[data-testid="invite-action"]');
    await expect(
      page.locator('[data-nav-key="members"][aria-current="page"]').first(),
    ).toBeVisible();
    await expect(action.locator("option")).toHaveCount(1);
    await expect(action).toContainText("Krapfentaxi 2026");
    await expect(action).not.toContainText("Krapfentaxi Nord 2026");
    await expect(
      page.locator('[data-testid="invite-role"] option'),
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

test("System-Admin erhält die global einladbaren Aktionen", async ({
  browser,
}) => {
  const { context, page } = await sessionPage(browser, systemSession);
  try {
    const action = page.locator('[data-testid="invite-action"]');
    await expect(action.locator("option")).toHaveCount(2);
    await expect(action).toContainText("Krapfentaxi 2026");
    await expect(action).toContainText("Krapfentaxi Nord 2026");
    await expect(action).not.toContainText("Krapfentaxi 2025");
  } finally {
    await context.close();
  }
});

test("Charity-Admin verwaltet den vollständigen Einladungsverlauf", async ({
  browser,
}) => {
  const { context, page } = await sessionPage(browser, klaraSession);
  try {
    await expect(
      page.getByRole("heading", { name: "Einladungen im Blick" }),
    ).toBeVisible();
    await expect(page.getByText("Foreign Lifecycle Pilot")).toHaveCount(0);
    await expect(page.locator(".invitation-card")).not.toHaveCount(0);

    const resendCard = page.locator(
      `[data-testid="invitation-${uiResendInvitationId}"]`,
    );
    await resendCard.getByTestId("invitation-resend").click();
    await expect(page.locator("#invitation-lifecycle-status")).toContainText(
      "Eine neue Einladung wurde versendet",
    );
    await expect(resendCard).toHaveAttribute("data-status", "revoked");

    const correctCard = page.locator(
      `[data-testid="invitation-${uiCorrectInvitationId}"]`,
    );
    await correctCard.getByTestId("invitation-correct-address").click();
    const correctedEmail = "ui-corrected-pilot@leonaid.invalid";
    await correctCard.getByLabel("Neue Login-E-Mail").fill(correctedEmail);
    await correctCard
      .getByRole("button", {
        name: "Korrigieren & senden",
      })
      .click();
    await expect(page.locator("#invitation-lifecycle-status")).toContainText(
      "korrigierte Adresse",
    );
    await expect(page.getByText(correctedEmail)).toBeVisible();
    await expect(correctCard).toHaveAttribute("data-status", "revoked");

    const revokeCard = page.locator(
      `[data-testid="invitation-${uiRevokeInvitationId}"]`,
    );
    await revokeCard.getByTestId("invitation-revoke").click();
    await expect(revokeCard).toContainText("Wirklich widerrufen?");
    await revokeCard.getByRole("button", { name: "Jetzt widerrufen" }).click();
    await expect(page.locator("#invitation-lifecycle-status")).toContainText(
      "wurde widerrufen",
    );
    await expect(revokeCard).toHaveAttribute("data-status", "revoked");

    await page.getByTestId("invitation-status-filter").selectOption("accepted");
    await expect(page.locator(".invitation-card")).not.toHaveCount(0);
    await expect(
      page.locator('.invitation-card[data-status="accepted"]'),
    ).not.toHaveCount(0);

    await page.screenshot({
      path: `${artifactDirectory}/invitation-lifecycle-admin.png`,
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});

test("Öffentliche Code-Eingabe ist mobil bedienbar", async ({ browser }) => {
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
