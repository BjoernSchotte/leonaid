import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const systemSession = process.env.SYSTEM_SESSION;
const charityAdminSession = process.env.KLARA_SESSION;
const annaSession = process.env.ANNA_SESSION;
const annaId = "10000000-0000-4000-8000-000000000004";
const activeActionId = "20000000-0000-4000-8000-000000000001";
const foreignActionId = "20000000-0000-4000-8000-000000000003";

if (
  !baseUrl ||
  !artifactDirectory ||
  !systemSession ||
  !charityAdminSession ||
  !annaSession
) {
  throw new Error("PILOT-012 Browserumgebung ist unvollständig");
}

test.setTimeout(90_000);

async function sessionContext(browser, token, viewport) {
  const context = await browser.newContext({
    viewport,
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
  return context;
}

async function selectAnna(page) {
  await page.goto(`${baseUrl}/admin/members`);
  await page
    .getByRole("searchbox", { name: "Mitglied suchen" })
    .fill("Anna Akquise");
  await page.getByRole("button", { name: "Suchen" }).click();
  await expect(page.getByTestId("member-card")).toHaveCount(1);
  await page.getByTestId("member-card").click();
  await expect(
    page.getByTestId("member-detail").getByRole("heading", {
      name: "Anna Akquise",
    }),
  ).toBeVisible();
}

async function changeRole(page, testId, enabled, expectedLabel) {
  const button = page.getByTestId(testId);
  await expect(button).toHaveText(enabled ? "Zuweisen" : "Entziehen");
  await button.click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await dialog
    .getByRole("button", {
      name: enabled ? "Rolle zuweisen" : "Rolle entziehen",
    })
    .click();
  await expect(page.getByTestId("member-role-success")).toContainText(
    expectedLabel,
  );
  await expect(button).toHaveText(enabled ? "Entziehen" : "Zuweisen");
}

async function restoreAnnaRoles(request) {
  const detail = await request.get(`${baseUrl}/api/v1/admin/members/${annaId}`);
  if (!detail.ok()) return;
  let member = await detail.json();

  const commands = [];
  if (member.globalRoles.includes("finance_reader")) {
    commands.push({
      path: `/api/v1/admin/members/${annaId}/global-roles/finance_reader`,
      enabled: false,
    });
  }
  for (const role of ["finance_reader", "driver", "charity_admin"]) {
    if (
      member.actionMemberships.some(
        (membership) =>
          membership.actionId === activeActionId && membership.role === role,
      )
    ) {
      commands.push({
        path: `/api/v1/admin/members/${annaId}/actions/${activeActionId}/roles/${role}`,
        enabled: false,
      });
    }
  }
  if (
    !member.actionMemberships.some(
      (membership) =>
        membership.actionId === activeActionId &&
        membership.role === "acquirer",
    )
  ) {
    commands.push({
      path: `/api/v1/admin/members/${annaId}/actions/${activeActionId}/roles/acquirer`,
      enabled: true,
    });
  }

  for (const command of commands) {
    const response = await request.patch(`${baseUrl}${command.path}`, {
      headers: {
        "Idempotency-Key": `pilot012:e2e:cleanup:${crypto.randomUUID()}`,
      },
      data: {
        enabled: command.enabled,
        expectedRevision: member.revision,
      },
    });
    expect(response.ok()).toBeTruthy();
    member = { ...member, revision: (await response.json()).revision };
  }
}

test("Charity-Admin verwaltet nur Aktionsrollen im eigenen Scope", async ({
  browser,
}) => {
  const context = await sessionContext(browser, charityAdminSession, {
    width: 1280,
    height: 960,
  });
  const page = await context.newPage();

  try {
    await selectAnna(page);
    await expect(
      page.getByText(
        "Du siehst ausschließlich Rollen in deinen verwalteten Aktionen.",
      ),
    ).toBeVisible();
    await expect(
      page.getByTestId("member-global-role-finance_reader"),
    ).toHaveCount(0);
    await expect(
      page.getByRole("heading", { name: "Krapfentaxi 2026" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Krapfentaxi 2025" }),
    ).toBeVisible();
    await expect(page.getByText("Krapfentaxi Nord 2026")).toHaveCount(0);

    const detailResponse = await context.request.get(
      `${baseUrl}/api/v1/admin/members/${annaId}`,
    );
    expect(detailResponse.ok()).toBeTruthy();
    const revision = (await detailResponse.json()).revision;
    const forbiddenGlobal = await context.request.patch(
      `${baseUrl}/api/v1/admin/members/${annaId}/global-roles/finance_reader`,
      {
        headers: {
          "Idempotency-Key": `pilot012:e2e:forbidden-global:${crypto.randomUUID()}`,
        },
        data: { enabled: true, expectedRevision: revision },
      },
    );
    expect(forbiddenGlobal.status()).toBe(403);
    expect((await forbiddenGlobal.json()).error.code).toBe(
      "system_admin_required",
    );
    const forbiddenForeign = await context.request.patch(
      `${baseUrl}/api/v1/admin/members/${annaId}/actions/${foreignActionId}/roles/finance_reader`,
      {
        headers: {
          "Idempotency-Key": `pilot012:e2e:forbidden-foreign:${crypto.randomUUID()}`,
        },
        data: { enabled: true, expectedRevision: revision },
      },
    );
    expect(forbiddenForeign.status()).toBe(403);
    expect((await forbiddenForeign.json()).error.code).toBe(
      "role_action_scope_forbidden",
    );

    const financeButtonId = `member-action-role-${activeActionId}-finance_reader`;
    await changeRole(page, financeButtonId, true, "Finanzen");
    await expect(page.getByTestId("member-membership")).toHaveCount(2);
    await changeRole(page, financeButtonId, false, "Finanzen");
    await expect(page.getByTestId("member-membership")).toHaveCount(1);

    const accessibility = await new AxeBuilder({ page }).analyze();
    expect(
      accessibility.violations.filter((violation) =>
        ["critical", "serious"].includes(violation.impact ?? ""),
      ),
    ).toEqual([]);
    await page.screenshot({
      path: `${artifactDirectory}/role-charity-scope.png`,
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});

test("System-Admin führt Rollenwechsel und vollständiges Offboarding über UI durch", async ({
  browser,
}) => {
  const systemContext = await sessionContext(browser, systemSession, {
    width: 1440,
    height: 1000,
  });
  const annaContext = await sessionContext(browser, annaSession, {
    width: 390,
    height: 844,
  });
  const systemPage = await systemContext.newPage();
  const annaPage = await annaContext.newPage();
  const annaWebPage = await annaContext.newPage();

  try {
    await annaPage.goto(`${baseUrl}/app/`);
    const annaMobileNavigation = annaPage.locator(".ui-pwa-tabbar");
    await expect(
      annaMobileNavigation.locator('[data-nav-key="sponsors"]'),
    ).toBeVisible();
    await selectAnna(systemPage);

    const globalFinanceId = "member-global-role-finance_reader";
    const actionFinanceId = `member-action-role-${activeActionId}-finance_reader`;
    const driverId = `member-action-role-${activeActionId}-driver`;
    const acquirerId = `member-action-role-${activeActionId}-acquirer`;

    await changeRole(systemPage, globalFinanceId, true, "Finanzen");
    await changeRole(systemPage, actionFinanceId, true, "Finanzen");
    await changeRole(systemPage, driverId, true, "Ausfahrer");
    await systemPage.screenshot({
      path: `${artifactDirectory}/roles-assigned.png`,
      fullPage: true,
    });

    await annaPage.reload();
    await expect(
      annaMobileNavigation.locator('[data-nav-key="sponsors"]'),
    ).toBeVisible();
    const identityWithDriver = await annaContext.request.get(
      `${baseUrl}/api/v1/identity/me`,
    );
    expect(identityWithDriver.ok()).toBeTruthy();
    expect(
      (await identityWithDriver.json()).navigation.some(
        (item) => item.surface === "pwa" && item.key === "delivery",
      ),
    ).toBeTruthy();
    await expect(
      annaMobileNavigation.locator('[data-nav-key="delivery"]'),
    ).toHaveAttribute("aria-disabled", "true");
    await annaWebPage.goto(`${baseUrl}/admin/`);
    await annaWebPage.getByTestId("mobile-menu").click();
    await expect(
      annaWebPage
        .locator(".ui-mobile-drawer")
        .locator('[data-nav-key="invoices"]'),
    ).toBeVisible();
    await annaWebPage
      .getByRole("button", { name: "Navigation schließen" })
      .click();

    await changeRole(systemPage, globalFinanceId, false, "Finanzen");
    await changeRole(systemPage, actionFinanceId, false, "Finanzen");
    await changeRole(systemPage, driverId, false, "Ausfahrer");
    await changeRole(systemPage, acquirerId, false, "Akquisiteur");
    await expect(
      systemPage.getByText("Derzeit keiner Charity-Aktion zugeordnet."),
    ).toBeVisible();
    await expect(
      systemPage.getByRole("heading", { name: "Globale Rollen" }),
    ).toHaveCount(0);

    await annaPage.reload();
    const mobileNavigation = annaPage.locator(".ui-pwa-tabbar");
    await expect(
      mobileNavigation.locator('[data-nav-key="overview-pwa"]'),
    ).toBeVisible();
    await expect(
      mobileNavigation.locator('[data-nav-key="sponsors"]'),
    ).toHaveCount(0);
    await expect(
      mobileNavigation.locator('[data-nav-key="delivery"]'),
    ).toHaveCount(0);
    await annaWebPage.reload();
    await expect(annaWebPage.locator('[data-nav-key="invoices"]')).toHaveCount(
      0,
    );

    const accessibility = await new AxeBuilder({
      page: systemPage,
    }).analyze();
    expect(
      accessibility.violations.filter((violation) =>
        ["critical", "serious"].includes(violation.impact ?? ""),
      ),
    ).toEqual([]);
    await systemPage.screenshot({
      path: `${artifactDirectory}/roles-offboarded.png`,
      fullPage: true,
    });
  } finally {
    await restoreAnnaRoles(systemContext.request);
    await annaContext.close();
    await systemContext.close();
  }
});
