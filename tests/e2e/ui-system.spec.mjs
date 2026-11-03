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

    // Option menu (cmdk in a Popover): search, Enter, number keys, Escape.
    const statusTrigger = page.getByRole("button", { name: "Status: Aktiv" });
    await statusTrigger.click();
    const statusMenu = page.getByRole("dialog", { name: "Status ändern" });
    const statusSearch = statusMenu.getByRole("combobox");
    await expect(statusSearch).toBeFocused();
    await expect(statusMenu).toHaveCSS("opacity", "1");
    await expect(statusMenu.getByRole("option")).toHaveCount(5);
    await expect(
      statusMenu.getByRole("option", { name: /Aktiv/ }),
    ).toHaveAttribute("aria-checked", "true");
    await expect(statusMenu).toHaveScreenshot("ui-system-option-menu.png", {
      animations: "disabled",
      caret: "hide",
      maxDiffPixelRatio: 0.001,
    });
    await expectNoSeriousAccessibilityViolations(page, "Auswahlmenü");
    await statusSearch.fill("arch");
    await expect(statusMenu.getByRole("option")).toHaveCount(1);
    await page.keyboard.press("Enter");
    await expect(statusMenu).toHaveCount(0);
    const archivedTrigger = page.getByRole("button", {
      name: "Status: Archiviert",
    });
    await expect(archivedTrigger).toBeFocused();
    await archivedTrigger.click();
    await expect(statusSearch).toBeFocused();
    await page.keyboard.press("2");
    await expect(
      page.getByRole("button", { name: "Status: Geplant" }),
    ).toBeFocused();

    const filterTrigger = page.getByRole("button", { name: "Filter (2)" });
    await filterTrigger.click();
    const filterMenu = page.getByRole("dialog", { name: "Filter wählen" });
    await expect(filterMenu.getByRole("combobox")).toBeFocused();
    await page.keyboard.type("Art");
    await page.keyboard.press("Enter");
    const kindMenu = page.getByRole("dialog", { name: "Filter Art" });
    await expect(kindMenu.getByRole("combobox")).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(
      kindMenu.getByRole("option", { name: /Krapfentaxi/ }),
    ).toHaveAttribute("aria-checked", "true");
    await expectNoSeriousAccessibilityViolations(page, "Mehrfachauswahl");
    await page.keyboard.press("Escape");
    await expect(kindMenu).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Filter (3)" }),
    ).toBeFocused();

    // A menu opened inside a modal <dialog> sits above it and stays usable.
    await page.getByRole("button", { name: "Im Dialog" }).click();
    const editDialog = page.getByRole("dialog", { name: "Aktion bearbeiten" });
    await expect(editDialog).toBeVisible();
    await editDialog.getByRole("button", { name: "Status: Geplant" }).click();
    const dialogMenu = page.getByRole("dialog", {
      name: "Status im Dialog ändern",
    });
    await expect(dialogMenu.getByRole("combobox")).toBeFocused();
    await expect(dialogMenu).toHaveCSS("opacity", "1");
    expect(
      await dialogMenu.evaluate((layer) => layer.matches(":popover-open")),
    ).toBe(true);
    await expectNoSeriousAccessibilityViolations(page, "Auswahlmenü im Dialog");
    // Escape closes only the menu, not the dialog around it.
    await page.keyboard.press("Escape");
    await expect(dialogMenu).toHaveCount(0);
    await expect(editDialog).toBeVisible();
    await editDialog.getByRole("button", { name: "Status: Geplant" }).click();
    // A real click: Playwright fails it if the option is covered or inert.
    await dialogMenu.getByRole("option", { name: /Abgeschlossen/ }).click();
    await expect(
      editDialog.getByRole("button", { name: "Status: Abgeschlossen" }),
    ).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(editDialog).toBeHidden();

    // Toasts stay visible above an open modal: the toaster moves into it.
    await expect(page.locator(".toaster-region").first()).toBeAttached();
    await page.evaluate(() => {
      window.__toastRegions = [...document.querySelectorAll(".toaster-region")];
    });
    await page.getByRole("button", { name: "Bestätigung öffnen" }).click();
    await expect(dialog.getByTestId("toast").first()).toBeVisible();
    // Dismissing a toast inside the open modal must not replay its rise.
    await dialog.evaluate((element) =>
      Promise.all(
        element
          .getAnimations({ subtree: true })
          .map((animation) => animation.finished),
      ),
    );
    await dialog
      .getByTestId("toast")
      .first()
      .getByRole("button", { name: "Meldung schließen" })
      .click();
    await expect(dialog.getByTestId("toast")).toHaveCount(0);
    expect(
      await dialog.evaluate((element) => ({
        animations: element.getAnimations({ subtree: true }).length,
        dialogAnimation: getComputedStyle(element).animationName,
        opacity: getComputedStyle(element.querySelector(".modal-body")).opacity,
      })),
    ).toEqual({ animations: 0, dialogAnimation: "none", opacity: "1" });
    await expect(dialog).toBeVisible();
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

async function createListDemoPage(browser, viewport) {
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
  await page.goto(`${baseUrl}/admin/system/ui?listview`);
  await expect(
    page.getByRole("heading", { level: 1, name: "Bestellungen" }),
  ).toBeVisible();
  return { context, page, pageErrors };
}

test("list view: keys, URL state, detail pane and bulk bar", async ({
  browser,
}) => {
  const { context, page, pageErrors } = await createListDemoPage(browser, {
    width: 1440,
    height: 1000,
  });

  try {
    const rows = page.locator(".row-link");
    await expect(page.getByText("7 von 24")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Zu prüfen", pressed: true }),
    ).toBeVisible();
    await expectNoSeriousAccessibilityViolations(page, "Liste");

    // j/k move the focus, Enter opens the pane, Esc closes it again.
    await page.keyboard.press("j");
    await page.keyboard.press("j");
    await page.keyboard.press("k");
    await expect(rows.first()).toBeFocused();
    await page.keyboard.press("Enter");
    const pane = page.getByRole("complementary", { name: /^Details: B-26-/ });
    await expect(pane).toBeVisible();
    await expect(page).toHaveURL(/[?&]open=b\d+/);
    await pane.evaluate((element) =>
      Promise.all(element.getAnimations().map((a) => a.finished)),
    );
    await expect(page).toHaveScreenshot("ui-system-list-pane.png", {
      animations: "disabled",
      caret: "hide",
      maxDiffPixelRatio: 0.001,
    });
    await expectNoSeriousAccessibilityViolations(page, "Liste mit Detail");
    await page.keyboard.press("j");
    await expect(rows.nth(1)).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(pane).toHaveCount(0);
    await expect(rows.nth(1)).toBeFocused();
    await expect(page).not.toHaveURL(/[?&]open=/);

    // x checks rows; the bulk bar edits all of them; Esc clears.
    await page.keyboard.press("x");
    await page.keyboard.press("k");
    await page.keyboard.press("x");
    const bulk = page.getByRole("region", { name: "Auswahl" });
    await expect(bulk).toContainText("2 ausgewählt");
    await expectNoSeriousAccessibilityViolations(page, "Bulk-Leiste");
    await page.keyboard.press("Escape");
    await expect(bulk).toHaveCount(0);

    // f opens the filter menu; keys are inert while typing in it.
    await page.keyboard.press("f");
    const filterMenu = page.getByRole("dialog", { name: "Filter wählen" });
    await expect(filterMenu.getByRole("combobox")).toBeFocused();
    await page.keyboard.type("Herk");
    await page.keyboard.press("Enter");
    const sourceMenu = page.getByRole("dialog", { name: "Filter Herkunft" });
    await expect(sourceMenu.getByRole("combobox")).toBeFocused();
    await page.keyboard.press("2");
    await expectNoSeriousAccessibilityViolations(page, "Filtermenü");
    await page.keyboard.press("Escape");
    await expect(sourceMenu).toHaveCount(0);
    await expect(page).toHaveURL(/f\.source=%C3%96ffentlich/);

    // / focuses the search; j types instead of moving.
    await page.keyboard.press("/");
    const search = page.getByRole("searchbox");
    await expect(search).toBeFocused();
    await page.keyboard.type("j");
    await expect(search).toHaveValue("j");
    await search.fill("");
    await page.keyboard.press("Escape");

    // The palette offers the list's commands.
    await page.keyboard.press("Control+k");
    const palette = page.getByRole("dialog", { name: "Befehlspalette" });
    await expect(palette).toBeVisible();
    await page.keyboard.type("Alle Bestellungen auswählen");
    await expect(
      palette.getByRole("option", { name: /Alle Bestellungen auswählen/ }),
    ).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(palette).toBeHidden();
    await expect(page.getByRole("region", { name: "Auswahl" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("region", { name: "Auswahl" })).toHaveCount(0);

    // The URL carries view, filters and grouping across a reload.
    await page.getByRole("button", { name: "Alle", exact: true }).click();
    await page
      .getByRole("combobox", { name: "Gruppieren nach" })
      .selectOption("status");
    const url = page.url();
    expect(url).toContain("view=all");
    expect(url).toContain("group=status");
    await page.reload();
    await expect(
      page.getByRole("button", { name: /^Alle/, pressed: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("combobox", { name: "Gruppieren nach" }),
    ).toHaveValue("status");
    await expect(page.getByText("24 Bestellungen")).toBeVisible();

    expect(pageErrors).toEqual([]);
  } finally {
    await context.close();
  }
});

test("list view: detail is a full-screen sheet at 390 px", async ({
  browser,
}) => {
  const { context, page, pageErrors } = await createListDemoPage(browser, {
    width: 390,
    height: 844,
  });

  try {
    await page.locator(".row-link").first().click();
    const sheet = page.getByRole("dialog", { name: /^Details: B-26-/ });
    await expect(sheet).toBeVisible();
    await sheet.evaluate((element) =>
      Promise.all(element.getAnimations().map((a) => a.finished)),
    );
    const box = await sheet.boundingBox();
    expect(
      box &&
        Object.fromEntries(
          Object.entries(box).map(([key, value]) => [key, Math.round(value)]),
        ),
    ).toEqual({ x: 0, y: 0, width: 390, height: 844 });
    await expect(page).toHaveScreenshot("ui-system-list-sheet.png", {
      animations: "disabled",
      caret: "hide",
      maxDiffPixelRatio: 0.001,
    });
    await expectNoSeriousAccessibilityViolations(page, "Detail mobil");
    await page.keyboard.press("Escape");
    await expect(sheet).toHaveCount(0);
    await expect(page).not.toHaveURL(/[?&]open=/);
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
