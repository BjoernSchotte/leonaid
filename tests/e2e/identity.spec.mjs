import { analyzeAccessibility } from "./axe.mjs";
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
    // The rail switcher lists only Klara's own campaigns.
    await page.getByTestId("campaign-switcher").click();
    const switcher = page.getByRole("dialog", { name: "Aktion wechseln" });
    await expect(
      switcher.getByRole("option", { name: /Krapfentaxi 2026/ }),
    ).toBeVisible();
    await expect(
      switcher.getByRole("option", { name: /Krapfentaxi 2025/ }),
    ).toBeVisible();
    await expect(
      switcher.getByRole("option", { name: /Krapfentaxi Nord/ }),
    ).toHaveCount(0);
    await page.keyboard.press("Escape");
    await page.screenshot({
      path: `${artifactDirectory}/charity-admin-desktop.png`,
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
    // One campaign: the app bar names it; the choice appears only for
    // several campaigns (ActionChoice in packages/features).
    await expect(page.getByTestId("current-action")).toHaveText(
      "Krapfentaxi 2026",
    );
    await expect(
      page.getByRole("combobox", { name: "Charity-Aktion" }),
    ).toHaveCount(0);
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

    const accessibility = await analyzeAccessibility(page);
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
