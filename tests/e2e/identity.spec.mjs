import AxeBuilder from "@axe-core/playwright";
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
  finance: process.env.FINN_SESSION,
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
    await expect(
      page.getByRole("heading", { name: "Guten Tag, Anna." }),
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
      mobileNavigation.locator('[data-nav-key="commitment"]'),
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
    await expect(
      page.getByRole("heading", { name: "Noch keine passende Charity-Aktion" }),
    ).toBeVisible();
  } finally {
    await context.close();
  }
});

test("System-Admin durchsucht, filtert und paginiert die vollständige Mitgliederliste", async ({
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
      page.getByRole("heading", { name: "Mitglieder verwalten" }),
    ).toBeVisible();
    await expect(page.getByText("Clubweite Ansicht")).toBeVisible();
    await expect(page.getByText("8 Mitglieder")).toBeVisible();
    await expect(page.getByTestId("member-card")).toHaveCount(6);
    await expect(
      page.getByTestId("member-detail").getByRole("heading", {
        name: "Anna Akquise",
      }),
    ).toBeVisible();

    await page.getByRole("button", { name: "Weiter" }).click();
    await expect(page.getByText("Seite 2")).toBeVisible();
    await expect(page.getByTestId("member-card")).toHaveCount(2);
    await expect(
      page.getByTestId("member-card").filter({ hasText: "Simone System" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Zurück" }).click();
    await expect(page.getByText("Seite 1")).toBeVisible();

    await page.getByTestId("member-status-filter").selectOption("suspended");
    await expect(page.getByText("1 Mitglied")).toBeVisible();
    await expect(page.getByTestId("member-card")).toHaveCount(1);
    await expect(
      page.getByTestId("member-card").filter({ hasText: "Gesa Gesperrt" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Filter zurücksetzen" }).click();

    await page
      .getByRole("searchbox", { name: "Mitglied suchen" })
      .fill("Klara");
    await page.getByRole("button", { name: "Suchen" }).click();
    await expect(page.getByTestId("member-card")).toHaveCount(1);
    await page.getByTestId("member-card").click();
    await expect(
      page.getByTestId("member-detail").getByRole("heading", {
        name: "Klara Kern",
      }),
    ).toBeVisible();

    await page.getByRole("tab", { name: /Mitgliederübersicht/ }).focus();
    await page.keyboard.press("ArrowRight");
    await expect(
      page.getByRole("tab", { name: /Mitglied einladen/ }),
    ).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("ArrowLeft");
    await expect(
      page.getByRole("tab", { name: /Mitgliederübersicht/ }),
    ).toHaveAttribute("aria-selected", "true");

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

test("Charity-Admin sieht mobil nur Mitglieder und Rollen eigener Aktionen", async ({
  browser,
}) => {
  const { context, page } = await sessionPage(
    browser,
    personas.charityAdmin,
    "/admin/members",
    { width: 390, height: 844 },
  );
  try {
    await expect(page.getByText("Ansicht deiner Aktionen")).toBeVisible();
    await expect(page.getByText("6 Mitglieder")).toBeVisible();
    const actionFilter = page.getByTestId("member-action-filter");
    await expect(actionFilter).toContainText("Krapfentaxi 2026");
    await expect(actionFilter).toContainText("Krapfentaxi 2025");
    await expect(actionFilter).not.toContainText("Krapfentaxi Nord 2026");
    await expect(page.getByText("Simone System", { exact: true })).toHaveCount(
      0,
    );
    await expect(page.getByText("Felix Fremd", { exact: true })).toHaveCount(0);

    await page.getByRole("searchbox", { name: "Mitglied suchen" }).fill("Anna");
    await page.getByRole("button", { name: "Suchen" }).click();
    await expect(page.getByTestId("member-card")).toHaveCount(1);
    await page.getByTestId("member-card").click();
    await expect(page.getByTestId("member-membership")).toHaveCount(1);
    await expect(
      page.getByRole("heading", { name: "Globale Rollen" }),
    ).toHaveCount(0);
    await expect(
      page.getByText(
        "Du siehst ausschließlich Rollen in deinen verwalteten Aktionen.",
      ),
    ).toBeVisible();

    await page.screenshot({
      path: `${artifactDirectory}/charity-members-mobile.png`,
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});

for (const [persona, token] of [
  ["Akquisiteur", personas.acquirer],
  ["Finanzen", personas.finance],
]) {
  test(`${persona} erhält auch über eine direkte URL keinen Mitgliederzugriff`, async ({
    browser,
  }) => {
    const { context, page } = await sessionPage(
      browser,
      token,
      "/admin/members",
      { width: 1024, height: 800 },
    );
    try {
      await expect(
        page.getByRole("heading", {
          name: "Mitglieder konnten nicht geladen werden",
        }),
      ).toBeVisible();
      await expect(page.getByTestId("member-card")).toHaveCount(0);
    } finally {
      await context.close();
    }
  });
}
