import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const simoneSession = process.env.SIMONE_SESSION;

if (!baseUrl || !artifactDirectory || !simoneSession) {
  throw new Error("POC-100 Browserumgebung ist unvollständig");
}

test.setTimeout(90_000);

function sessionCookie(value) {
  return {
    name: "__Host-leonaid_session",
    value,
    url: baseUrl,
    httpOnly: true,
    secure: true,
    sameSite: "Lax",
  };
}

async function expectNoSeriousAccessibilityViolations(page, context) {
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(
    accessibility.violations.filter(
      (violation) =>
        violation.impact === "critical" || violation.impact === "serious",
    ),
    context,
  ).toEqual([]);
}

async function createCatalogPage(browser, viewport) {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport,
  });
  await context.addCookies([sessionCookie(simoneSession)]);
  await context.addInitScript(() => {
    window.localStorage.setItem("leonaid.theme", "light");
    window.localStorage.setItem("leonaid.sidebar-collapsed", "false");
  });
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.goto(`${baseUrl}/admin/system/ui`);
  await expect(
    page.getByRole("heading", { level: 1, name: "LeonAid Komponenten" }),
  ).toBeVisible();
  return { context, page, pageErrors };
}

test("UI-Katalog belegt alle Basiszustände mit realer Identität", async ({
  browser,
}) => {
  const { context, page, pageErrors } = await createCatalogPage(browser, {
    width: 1440,
    height: 1000,
  });

  try {
    await expect(page.getByText("Backend verbunden")).toBeVisible();
    const catalog = page.getByTestId("ui-catalog");
    await expect(
      catalog.getByText("Simone System", { exact: true }).first(),
    ).toBeVisible();
    await expect(
      catalog.getByText("System-Admin", { exact: true }).first(),
    ).toBeVisible();
    await expect(page.getByTestId("current-action")).toHaveText("UI-Basis");
    await expect(
      page.getByRole("table", {
        name: "Rollen und Zuständigkeiten der angemeldeten Person",
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Aktionen und Fokus" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Feedback und Bestätigung" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Formulare und Fehler" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Tabelle und Leerzustand" }),
    ).toBeVisible();

    await expect(page).toHaveScreenshot("ui-system-desktop.png", {
      animations: "disabled",
      caret: "hide",
      maxDiffPixelRatio: 0.001,
    });
    await page.screenshot({
      path: `${artifactDirectory}/ui-system-desktop.png`,
      fullPage: false,
    });
    await expectNoSeriousAccessibilityViolations(page, "Katalog Light");

    await page.keyboard.press("Tab");
    await expect(
      page.getByRole("link", { name: "Zum Hauptinhalt" }),
    ).toBeFocused();

    await page.getByRole("button", { name: "Toast anzeigen" }).click();
    const toast = page.getByTestId("toast");
    await expect(toast).toContainText("Änderung gespeichert");
    await toast.hover();
    await page.getByRole("button", { name: "Hinweis schließen" }).click();
    await expect(toast).toHaveCount(0);

    await page.getByRole("button", { name: "Toast anzeigen" }).click();
    await expect(page.getByTestId("toast")).toContainText(
      "Änderung gespeichert",
    );
    await expectNoSeriousAccessibilityViolations(page, "Toast");

    await page.getByRole("button", { name: "Bestätigung öffnen" }).click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toContainText("Kritische Aktion bestätigen?");
    await expectNoSeriousAccessibilityViolations(page, "Bestätigungsdialog");
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Bestätigung öffnen" }),
    ).toBeFocused();

    await page.getByTestId("sidebar-toggle").click();
    await expect(page.locator(".ui-shell")).toHaveAttribute(
      "data-sidebar-collapsed",
      "true",
    );
    await page.screenshot({
      path: `${artifactDirectory}/ui-system-desktop-collapsed.png`,
      fullPage: false,
    });

    await page.getByTestId("theme-trigger").click();
    await page.getByTestId("theme-dark").click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expectNoSeriousAccessibilityViolations(page, "Katalog Dark");
    await page.screenshot({
      path: `${artifactDirectory}/ui-system-dark.png`,
      fullPage: false,
    });

    expect(pageErrors).toEqual([]);
  } finally {
    await context.close();
  }
});

test("mobile Shell hält Rolle und Arbeitskontext sichtbar", async ({
  browser,
}) => {
  const { context, page, pageErrors } = await createCatalogPage(browser, {
    width: 390,
    height: 844,
  });

  try {
    await expect(page.getByTestId("desktop-sidebar")).toBeHidden();
    const workContext = page.getByTestId("mobile-work-context");
    await expect(workContext).toContainText("System-Admin");
    await expect(workContext).toContainText("UI-Basis");

    await expect(page).toHaveScreenshot("ui-system-mobile.png", {
      animations: "disabled",
      caret: "hide",
      maxDiffPixelRatio: 0.001,
    });
    await page.screenshot({
      path: `${artifactDirectory}/ui-system-mobile.png`,
      fullPage: false,
    });

    await page.getByTestId("mobile-menu").click();
    const drawer = page.getByRole("dialog", { name: "Navigation" });
    await expect(drawer).toBeVisible();
    await expect(drawer.getByTestId("current-action")).toHaveText("UI-Basis");
    await expectNoSeriousAccessibilityViolations(page, "Mobile Navigation");
    await page.keyboard.press("Escape");
    await expect(drawer).toHaveCount(0);

    expect(pageErrors).toEqual([]);
  } finally {
    await context.close();
  }
});
