import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./csp-guard.mjs";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const simoneSession = process.env.SIMONE_SESSION;

if (!baseUrl || !artifactDirectory || !simoneSession) {
  throw new Error("POC-100 browser environment is incomplete");
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

test("UI catalog proves all base states with real identity", async ({
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
    await page.getByRole("button", { name: "Meldung schließen" }).click();
    await expect(toast).toHaveCount(0);

    await page.getByRole("button", { name: "Toast anzeigen" }).click();
    await expect(page.getByTestId("toast")).toContainText(
      "Änderung gespeichert",
    );
    // axe measures contrast through opacity; wait until the fade-in ends.
    await expect(page.getByTestId("toast")).toHaveCSS("opacity", "1");
    await expectNoSeriousAccessibilityViolations(page, "Toast");

    await page.getByRole("button", { name: "Bestätigung öffnen" }).click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toContainText("Kritische Aktion bestätigen?");
    // axe measures contrast through opacity; wait until the rise ends.
    await dialog.evaluate((element) =>
      Promise.all(
        element.getAnimations().map((animation) => animation.finished),
      ),
    );
    await expectNoSeriousAccessibilityViolations(page, "Bestätigungsdialog");
    await expect(page.locator("html")).toHaveCSS("overflow-y", "hidden");
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(page.locator("html")).not.toHaveCSS("overflow-y", "hidden");
    await expect(
      page.getByRole("button", { name: "Bestätigung öffnen" }),
    ).toBeFocused();

    // Toasts stay visible above an open modal: the toaster moves into it.
    await expect(page.locator(".toaster-region").first()).toBeAttached();
    await page.evaluate(() => {
      window.__toastRegions = [...document.querySelectorAll(".toaster-region")];
    });
    await page.getByRole("button", { name: "Bestätigung öffnen" }).click();
    await expect(dialog.getByTestId("toast").first()).toBeVisible();
    // Confirm closes the dialog and shows the result in the same update;
    // the result lands in the same, already connected live regions.
    await dialog.getByRole("button", { name: "Aktion bestätigen" }).click();
    await expect(dialog).toHaveCount(0);
    const result = page
      .getByTestId("toast")
      .filter({ hasText: "Bestätigung abgeschlossen" });
    await expect(result).toBeVisible();
    expect(
      await page.evaluate(() => {
        const regions = [...document.querySelectorAll(".toaster-region")];
        return (
          regions.length === 2 &&
          regions.every(
            (region, index) => region === window.__toastRegions[index],
          ) &&
          regions.every((region) => !region.closest("dialog")) &&
          regions[0].textContent.includes("Bestätigung abgeschlossen")
        );
      }),
    ).toBe(true);

    await page.getByTestId("sidebar-toggle").click();
    await expect(page.locator(".ui-shell")).toHaveAttribute(
      "data-sidebar-collapsed",
      "true",
    );
    await page.screenshot({
      path: `${artifactDirectory}/ui-system-desktop-collapsed.png`,
      fullPage: false,
    });

    const themeMenu = page.getByRole("menu");
    await page.getByTestId("theme-trigger").click();
    await expect(themeMenu).toHaveCSS("opacity", "1");
    await expectNoSeriousAccessibilityViolations(page, "Farbschema-Menü Light");
    await page.getByTestId("theme-dark").click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(page.locator(".ui-theme-menu")).toHaveCount(0);
    await expectNoSeriousAccessibilityViolations(page, "Katalog Dark");
    await page.getByTestId("theme-trigger").click();
    await expect(themeMenu).toHaveCSS("opacity", "1");
    await expectNoSeriousAccessibilityViolations(page, "Farbschema-Menü Dark");
    await page.keyboard.press("Escape");
    await expect(page.locator(".ui-theme-menu")).toHaveCount(0);
    await expect(page.getByTestId("theme-trigger")).toBeFocused();
    await page.screenshot({
      path: `${artifactDirectory}/ui-system-dark.png`,
      fullPage: false,
    });

    expect(pageErrors).toEqual([]);
  } finally {
    await context.close();
  }
});

test("uses self-hosted Leitsystem fonts", async ({ browser }) => {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1440, height: 1000 },
  });
  await context.addCookies([sessionCookie(simoneSession)]);
  const page = await context.newPage();
  const appOrigin = new URL(baseUrl).origin;
  const foreignRequests = [];
  const fontResponses = [];
  page.on("request", (request) => {
    const url = request.url();
    if (/^https?:/.test(url) && new URL(url).origin !== appOrigin) {
      foreignRequests.push(url);
    }
  });
  page.on("response", (response) => {
    if (response.request().resourceType() === "font") {
      fontResponses.push({ url: response.url(), status: response.status() });
    }
  });

  try {
    await page.goto(`${baseUrl}/admin/system/ui`);
    await expect(
      page.getByRole("heading", { level: 1, name: "LeonAid Komponenten" }),
    ).toBeVisible();
    const fonts = await page.evaluate(async () => {
      await document.fonts.ready;
      // Faces load lazily; request them so the check proves they are served.
      await document.fonts.load("700 16px Barlow");
      await document.fonts.load('16px "JetBrains Mono Variable"');
      // check() is also true for families without any @font-face, so the
      // loaded faces are listed as well.
      const loaded = [...document.fonts]
        .filter((face) => face.status === "loaded")
        .map((face) => `${face.family.replaceAll('"', "")} ${face.weight}`);
      return {
        loaded,
        barlow: document.fonts.check("16px Barlow"),
        barlowBold: document.fonts.check("700 16px Barlow"),
        mono: document.fonts.check('16px "JetBrains Mono Variable"'),
        body: getComputedStyle(document.body).fontFamily,
      };
    });
    expect(fonts.loaded).toEqual(
      expect.arrayContaining(["Barlow 400", "Barlow 700"]),
    );
    expect(
      fonts.loaded.some((face) => face.startsWith("JetBrains Mono Variable")),
    ).toBe(true);
    expect(fonts.barlow).toBe(true);
    expect(fonts.barlowBold).toBe(true);
    expect(fonts.mono).toBe(true);
    expect(fonts.body).toMatch(/^"?Barlow"?,/);
    expect(fontResponses.length).toBeGreaterThan(0);
    for (const font of fontResponses) {
      expect(new URL(font.url).origin, font.url).toBe(appOrigin);
      expect(new URL(font.url).pathname, font.url).toMatch(
        /^\/admin\/assets\/.+\.woff2$/,
      );
      expect(font.status, font.url).toBe(200);
    }
    expect(foreignRequests).toEqual([]);
  } finally {
    await context.close();
  }
});

test("mobile shell keeps role and work context visible", async ({
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
