import { expect, test } from "@playwright/test";

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
    throw new Error(`${name}: echte Sitzung fehlt`);
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
  await expect(page.locator('[data-testid="display-name"]')).toBeVisible();
  return { context, page };
}

test("Charity-Admin sieht nur eigene Aktionen und keine Systemnavigation", async ({
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
    await expect(page.locator('[data-testid="action-list"]')).toContainText(
      "Krapfentaxi 2026",
    );
    await expect(page.locator('[data-testid="action-list"]')).toContainText(
      "Krapfentaxi 2025",
    );
    await expect(page.locator('[data-testid="action-list"]')).not.toContainText(
      "Krapfentaxi Nord 2026",
    );
    await page.screenshot({
      path: `${artifactDirectory}/charity-admin-desktop.png`,
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});

test("Akquisiteur erhält auf dem Smartphone nur seine Akquise-Aufgaben", async ({
  browser,
}) => {
  const { context, page } = await sessionPage(
    browser,
    personas.acquirer,
    "/app/",
    { width: 390, height: 844 },
  );
  try {
    const mobileNavigation = page.locator(".ui-pwa-tabbar");
    await expect(page.locator('[data-testid="display-name"]')).toHaveText(
      "Anna Akquise",
    );
    await expect(page.locator('[data-testid="roles"]')).toContainText(
      "Akquisiteur",
    );
    await expect(mobileNavigation).toBeVisible();
    await expect(
      mobileNavigation.locator('[data-nav-key="sponsors"]'),
    ).toBeVisible();
    await expect(
      mobileNavigation.locator('[data-nav-key="activities"]'),
    ).toBeVisible();
    await expect(
      mobileNavigation.locator('[data-nav-key="commitment"]'),
    ).toBeVisible();
    await expect(page.locator('[data-nav-key="system"]')).toHaveCount(0);
    await expect(page.locator('[data-nav-key="members"]')).toHaveCount(0);
    await expect(page.locator('[data-nav-key="invoices"]')).toHaveCount(0);
    await expect(page.locator('[data-testid="action-list"]')).toContainText(
      "Krapfentaxi 2026",
    );
    await expect(
      page.locator('[data-testid="action-list"] article'),
    ).toHaveCount(1);
    await page.screenshot({
      path: `${artifactDirectory}/acquirer-mobile.png`,
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});

test("System-Admin erkennt seinen globalen, aktionsunabhängigen Bereich", async ({
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
    await expect(page.locator('[data-testid="action-list"]')).toContainText(
      "Noch keine verwaltete Aktion",
    );
  } finally {
    await context.close();
  }
});
