import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./csp-guard.mjs";
import {
  memberPane,
  memberRow,
  memberRows,
  openMember,
  searchMembers,
} from "./member-list.mjs";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;

if (!baseUrl || !artifactDirectory) {
  throw new Error(
    "LEONAID_E2E_BASE_URL und LEONAID_E2E_ARTIFACT_DIR sind erforderlich",
  );
}

const personas = {
  system: process.env.SYSTEM_SESSION,
  charityAdmin: process.env.KLARA_SESSION,
  acquirer: process.env.ANNA_SESSION,
  finance: process.env.FINN_SESSION,
};

for (const [name, token] of Object.entries(personas)) {
  if (!token) {
    throw new Error(`${name}: real session missing`);
  }
}

async function sessionPage(browser, token, path, viewport) {
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
  const page = await context.newPage();
  await page.goto(`${baseUrl}${path}`);
  return { context, page };
}

test("charity admin sees only own actions and no system navigation", async ({
  browser,
}) => {
  const { context, page } = await sessionPage(
    browser,
    personas.charityAdmin,
    "/admin/",
    { width: 1440, height: 1000 },
  );
  try {
    await expect(page.locator('[data-testid="display-name"]')).toHaveText(
      "Klara Kern",
    );
    await expect(page.locator('[data-testid="roles"]')).toContainText(
      "Charity-Admin",
    );
    await expect(
      page.locator('[data-nav-key="members"]').first(),
    ).toBeVisible();
    await expect(
      page.locator('[data-nav-key="invoices"]').first(),
    ).toBeVisible();
    await expect(page.locator('[data-nav-key="system"]')).toHaveCount(0);
    const actionSelector = page.getByRole("combobox", {
      name: "Charity-Aktion",
    });
    await expect(actionSelector).toContainText("Krapfentaxi 2026");
    await expect(actionSelector).toContainText("Krapfentaxi 2025");
    await expect(actionSelector).not.toContainText("Krapfentaxi Nord 2026");
    await page.screenshot({
      path: `${artifactDirectory}/charity-admin-desktop.png`,
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});

test("acquirer gets only their acquisition tasks on a smartphone", async ({
  browser,
}) => {
  const { context, page } = await sessionPage(
    browser,
    personas.acquirer,
    "/app/",
    { width: 390, height: 844 },
  );
  try {
    const mobileNavigation = page.locator(".pwa-tabs");
    await expect(
      page.getByRole("heading", { name: /^Guten (Morgen|Tag|Abend), Anna\.$/ }),
    ).toBeVisible();
    await expect(
      page.getByRole("combobox", { name: "Charity-Aktion" }),
    ).toContainText("Krapfentaxi 2026");
    await expect(mobileNavigation).toBeVisible();
    await expect(
      mobileNavigation.locator('[data-nav-key="sponsors"]'),
    ).toBeVisible();
    await expect(
      mobileNavigation.locator('[data-nav-key="activities"]'),
    ).toBeVisible();
    await expect(
      mobileNavigation.locator('[data-nav-key="sponsor-new"]'),
    ).toBeVisible();
    await expect(page.locator('[data-nav-key="system"]')).toHaveCount(0);
    await expect(page.locator('[data-nav-key="members"]')).toHaveCount(0);
    await expect(page.locator('[data-nav-key="invoices"]')).toHaveCount(0);
    await expect(
      page.getByRole("combobox", { name: "Charity-Aktion" }).locator("option"),
    ).toHaveCount(1);
    await page.screenshot({
      path: `${artifactDirectory}/acquirer-mobile.png`,
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});

test("acquirer-only member is redirected from the back office to the PWA", async ({
  browser,
}) => {
  const { context, page } = await sessionPage(
    browser,
    personas.acquirer,
    "/admin/",
    { width: 1280, height: 900 },
  );
  try {
    await page.waitForURL(`${baseUrl}/app/`);
    await expect(
      page.getByRole("heading", { name: /^Guten (Morgen|Tag|Abend), Anna\.$/ }),
    ).toBeVisible();
    await expect(
      page.getByRole("combobox", { name: "Charity-Aktion" }),
    ).toContainText("Krapfentaxi 2026");
    await expect(page.locator('[data-nav-key="overview-web"]')).toHaveCount(0);

    await page.goto(`${baseUrl}/admin/members`);
    await page.waitForURL(`${baseUrl}/app/`);
    await expect(
      page.getByRole("heading", { name: /^Guten (Morgen|Tag|Abend), Anna\.$/ }),
    ).toBeVisible();
    await page.screenshot({
      path: `${artifactDirectory}/acquirer-admin-redirect.png`,
      fullPage: true,
    });
    // The survey module is available without granting unrelated backoffice roles.
    await page.goto(`${baseUrl}/admin/surveys`);
    await expect(
      page.getByRole("heading", { name: "Umfragen", exact: true }),
    ).toBeVisible();
    await expect(
      page.locator('[data-nav-key="surveys"]').first(),
    ).toBeVisible();
    for (const key of ["overview-web", "members", "system", "invoices"]) {
      await expect(page.locator(`[data-nav-key="${key}"]`)).toHaveCount(0);
    }
  } finally {
    await context.close();
  }
});

test("system admin recognizes the global, action-independent area", async ({
  browser,
}) => {
  const { context, page } = await sessionPage(
    browser,
    personas.system,
    "/admin/",
    { width: 1024, height: 800 },
  );
  try {
    await expect(page.locator('[data-testid="display-name"]')).toHaveText(
      "Simone System",
    );
    await expect(page.locator('[data-testid="roles"]')).toContainText(
      "System-Admin",
    );
    await expect(page.locator('[data-nav-key="system"]').first()).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Noch keine passende Charity-Aktion" }),
    ).toBeVisible();
  } finally {
    await context.close();
  }
});

test("system admin searches, filters and opens the full member list", async ({
  browser,
}) => {
  const { context, page } = await sessionPage(
    browser,
    personas.system,
    "/admin/members",
    { width: 1440, height: 1000 },
  );
  try {
    await expect(
      page.getByRole("heading", { level: 1, name: "Mitglieder" }),
    ).toBeVisible();
    await expect(page.locator(".listview .page-count")).toHaveText(
      "8 Mitglieder",
    );
    // The list loads every member; there are no pages any more.
    await expect(memberRows(page)).toHaveCount(8);
    await expect(page.getByTestId("member-scope-note")).toHaveCount(0);

    const views = page.getByRole("navigation", {
      name: "Gespeicherte Ansichten",
    });
    await views.getByRole("button", { name: "Gesperrt", exact: true }).click();
    await expect(page).toHaveURL(/\/admin\/members\?view=blocked$/);
    await expect(memberRows(page)).toHaveCount(1);
    await expect(memberRow(page, "Gesa Gesperrt")).toBeVisible();
    await expect(page.locator(".listview .page-count")).toHaveText("1 von 8");
    await views.getByRole("button", { name: "Alle", exact: true }).click();
    await expect(memberRows(page)).toHaveCount(8);

    await searchMembers(page, "Klara");
    await expect(memberRows(page)).toHaveCount(1);
    const pane = await openMember(page, "Klara Kern");
    await expect(pane.getByTestId("member-detail-status")).toHaveText("Aktiv");
    expect(new URL(page.url()).searchParams.get("open")).toBeTruthy();

    // The URL keeps the open member across a reload.
    await page.reload();
    await expect(memberPane(page)).toBeVisible();
    await expect(
      page.getByRole("heading", { level: 2, name: "Klara Kern", exact: true }),
    ).toBeVisible();

    const accessibility = await new AxeBuilder({ page }).analyze();
    expect(
      accessibility.violations.filter((violation) =>
        ["critical", "serious"].includes(violation.impact ?? ""),
      ),
    ).toEqual([]);
    await page.screenshot({
      path: `${artifactDirectory}/system-members-desktop.png`,
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});

test("charity admin sees on mobile only members and roles of own actions", async ({
  browser,
}) => {
  const { context, page } = await sessionPage(
    browser,
    personas.charityAdmin,
    "/admin/members",
    { width: 390, height: 844 },
  );
  try {
    await expect(page.getByTestId("member-scope-note")).toContainText(
      "Ansicht Ihrer Aktionen.",
    );
    await expect(page.locator(".listview .page-count")).toHaveText(
      "6 Mitglieder",
    );
    await expect(memberRow(page, "Simone System")).toHaveCount(0);
    await expect(memberRow(page, "Felix Fremd")).toHaveCount(0);

    const pane = await openMember(page, "Anna Akquise");
    await expect(page.locator("dialog.pane-sheet")).toBeVisible();
    await expect(pane.getByTestId("member-membership")).toHaveCount(1);
    const actions = pane.getByTestId("member-role-add-action");
    await expect(actions).toContainText("Krapfentaxi 2026");
    await expect(actions).toContainText("Krapfentaxi 2025");
    await expect(actions).not.toContainText("Krapfentaxi Nord 2026");
    await expect(pane.getByText("Systemrollen")).toHaveCount(0);
    await expect(pane.getByTestId("member-scope-pane-note")).toBeVisible();

    await page.screenshot({
      path: `${artifactDirectory}/charity-members-mobile.png`,
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});

test("finance gets no member access, even through a direct URL", async ({
  browser,
}) => {
  const { context, page } = await sessionPage(
    browser,
    personas.finance,
    "/admin/members",
    { width: 1024, height: 800 },
  );
  try {
    await expect(
      page.getByRole("heading", {
        name: "Mitglieder konnten nicht geladen werden",
      }),
    ).toBeVisible();
    await expect(memberRows(page)).toHaveCount(0);
  } finally {
    await context.close();
  }
});
