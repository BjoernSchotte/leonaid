import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./csp-guard.mjs";
import { changeRole, memberPane, openMember } from "./member-list.mjs";

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
  throw new Error("PILOT-012 browser environment is incomplete");
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
  await openMember(page, "Anna Akquise");
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

test("charity admin manages only action roles in their own scope", async ({
  browser,
}) => {
  const context = await sessionContext(browser, charityAdminSession, {
    width: 1280,
    height: 960,
  });
  const page = await context.newPage();

  try {
    await selectAnna(page);
    const pane = memberPane(page);
    await expect(pane.getByTestId("member-scope-pane-note")).toHaveText(
      "Sie sehen ausschließlich Rollen in Ihren verwalteten Aktionen. Globale Rollen bleiben ausgeblendet.",
    );
    await expect(pane.getByTestId("member-global-role-add")).toHaveCount(0);
    await expect(pane.getByText("Systemrollen")).toHaveCount(0);
    const manageable = pane.getByTestId("member-role-add-action");
    await expect(manageable).toContainText("Krapfentaxi 2026");
    await expect(manageable).toContainText("Krapfentaxi 2025");
    await expect(manageable).not.toContainText("Krapfentaxi Nord 2026");
    await expect(pane.getByText("Krapfentaxi Nord 2026")).toHaveCount(0);

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

    const finance = {
      actionId: activeActionId,
      role: "finance_reader",
      label: "Finanzen",
    };
    await changeRole(page, { ...finance, enabled: true });
    await expect(pane.getByTestId("member-membership")).toHaveCount(2);
    await changeRole(page, { ...finance, enabled: false });
    await expect(pane.getByTestId("member-membership")).toHaveCount(1);

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

test("system admin performs a role change and full offboarding through the UI", async ({
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
    const annaMobileNavigation = annaPage.locator(".pwa-tabs");
    await expect(
      annaMobileNavigation.locator('[data-nav-key="sponsors"]'),
    ).toBeVisible();
    await selectAnna(systemPage);

    const globalFinance = { role: "finance_reader", label: "Finanzen" };
    const actionFinance = {
      actionId: activeActionId,
      role: "finance_reader",
      label: "Finanzen",
    };
    const driver = {
      actionId: activeActionId,
      role: "driver",
      label: "Ausfahrer",
    };
    const acquirer = {
      actionId: activeActionId,
      role: "acquirer",
      label: "Akquisiteur",
    };

    await changeRole(systemPage, { ...globalFinance, enabled: true });
    await changeRole(systemPage, { ...actionFinance, enabled: true });
    await changeRole(systemPage, { ...driver, enabled: true });
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
    await annaPage.getByTestId("pwa-menu").click();
    const annaPwaSheet = annaPage.getByRole("dialog", { name: "Mehr" });
    // The driver role opens the delivery board in the app (Task 6.2).
    const deliveryTile = annaPwaSheet.locator('[data-nav-key="delivery"]');
    await expect(deliveryTile).toHaveAttribute("href", "/app/delivery");
    await expect(deliveryTile).not.toHaveAttribute("aria-disabled", "true");
    await annaPwaSheet.getByRole("button", { name: "Schließen" }).click();
    await annaWebPage.goto(`${baseUrl}/admin/`);
    await annaWebPage.getByTestId("mobile-menu").click();
    const annaSheet = annaWebPage.getByRole("dialog", {
      name: "Alle Bereiche",
    });
    await expect(annaSheet.locator('[data-nav-key="invoices"]')).toBeVisible();
    await annaSheet.getByRole("button", { name: "Schließen" }).click();

    await changeRole(systemPage, { ...globalFinance, enabled: false });
    await changeRole(systemPage, { ...actionFinance, enabled: false });
    await changeRole(systemPage, { ...driver, enabled: false });
    await changeRole(systemPage, { ...acquirer, enabled: false });
    const systemPane = memberPane(systemPage);
    await expect(
      systemPane.getByText("Derzeit keiner Charity-Aktion zugeordnet."),
    ).toBeVisible();
    await expect(systemPane.getByTestId("member-global-role")).toHaveCount(0);
    await expect(systemPane.getByText("Keine Systemrollen.")).toBeVisible();

    await annaPage.reload();
    const mobileNavigation = annaPage.locator(".pwa-tabs");
    await expect(
      mobileNavigation.locator('[data-nav-key="overview-pwa"]'),
    ).toBeVisible();
    await expect(
      mobileNavigation.locator('[data-nav-key="sponsors"]'),
    ).toHaveCount(0);
    await annaPage.getByTestId("pwa-menu").click();
    await expect(
      annaPage
        .getByRole("dialog", { name: "Mehr" })
        .locator('[data-nav-key="delivery"]'),
    ).toHaveCount(0);
    await annaPage
      .getByRole("dialog", { name: "Mehr" })
      .getByRole("button", { name: "Schließen" })
      .click();
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
