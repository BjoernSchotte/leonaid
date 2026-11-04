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

/**
 * Lets finite CSS animations end before axe measures colours. A popover
 * fades in over 120 ms (opacity); axe blends text and ground with the
 * current opacity, so a scan during the fade reports the list menu's
 * 14.5:1 label as 4.39:1. Endless animations (spinner, shimmer) are skipped.
 */
async function settleAnimations(page) {
  await page.evaluate(() =>
    Promise.all(
      document
        .getAnimations()
        .filter((animation) =>
          Number.isFinite(animation.effect?.getComputedTiming().endTime),
        )
        .map((animation) => animation.finished.catch(() => undefined)),
    ),
  );
}

async function expectNoSeriousAccessibilityViolations(page, context) {
  await settleAnimations(page);
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
    // Ordinary pages keep the page frame (padding, 1320 px cap).
    await expect(page.locator(".page")).toHaveCSS("padding-left", "32px");
    await expect(page.locator(".page")).toHaveCSS("max-width", "1320px");
    const catalog = page.getByTestId("ui-catalog");
    await expect(
      catalog.getByText("Simone System", { exact: true }).first(),
    ).toBeVisible();
    await expect(
      catalog.getByText("System-Admin", { exact: true }).first(),
    ).toBeVisible();
    await expect(page.getByTestId("topbar-zone")).toHaveText("System");
    await expect(page.getByTestId("rail-shell")).toHaveAttribute(
      "data-zone",
      "system",
    );
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
      page.getByRole("link", { name: "Zum Inhalt springen" }),
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

    // ≤ 1024 px: the rail collapses to its icon column.
    await page.setViewportSize({ width: 1024, height: 1000 });
    const rail = page.getByTestId("desktop-sidebar");
    await expect(rail).toBeVisible();
    expect((await rail.boundingBox()).width).toBe(72);
    await expect(
      rail.getByRole("link", { name: "System" }).locator(".nav-label"),
    ).toBeHidden();
    await page.screenshot({
      path: `${artifactDirectory}/ui-system-desktop-collapsed.png`,
      fullPage: false,
    });
    await page.setViewportSize({ width: 1440, height: 1000 });

    const themeToggle = page.getByTestId("theme-toggle");
    await expect(themeToggle).toHaveAccessibleName(
      "Dunkle Darstellung (Umschalt+T)",
    );
    await themeToggle.click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(themeToggle).toHaveAccessibleName(
      "Helle Darstellung (Umschalt+T)",
    );
    await expect(themeToggle).toBeFocused();
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
    await expect(page.getByRole("region", { name: "Auswahl" })).toContainText(
      "24 ausgewählt",
    );
    await page.keyboard.press("Escape");
    await expect(page.getByRole("region", { name: "Auswahl" })).toHaveCount(0);

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

test("charts: token colours under the strict CSP, theme redraw, resize", async ({
  browser,
}) => {
  const { context, page, pageErrors } = await createCatalogPage(browser, {
    width: 1440,
    height: 1000,
  });
  try {
    const charts = page.getByTestId("ui-catalog-charts");
    await charts.scrollIntoViewIfNeeded();
    const canvases = charts.locator("canvas[role=img]");
    await expect(canvases).toHaveCount(3);
    await expect(canvases.nth(1)).toHaveAttribute("aria-label", /3: < 5/);
    await expect(
      charts.getByRole("list", { name: "Legende: Empfehlung" }),
    ).toContainText("Förderer (9–10)16 (53 %)");
    // The first matrix segment uses --chart-pos, read from canvas pixels.
    const pixel = () =>
      canvases.nth(2).evaluate((canvas) => {
        const ctx = canvas.getContext("2d");
        const ratio = canvas.width / canvas.clientWidth;
        const [r, g, b] = ctx.getImageData(
          Math.round(canvas.width * 0.35),
          Math.round(18 * ratio),
          1,
          1,
        ).data;
        return `${r},${g},${b}`;
      });
    const light = await pixel();
    await charts.getByText("Als Tabelle anzeigen").click();
    await expect(charts.getByRole("table")).toContainText("< 5");
    await expect(charts).toHaveScreenshot("ui-system-charts.png", {
      animations: "disabled",
      caret: "hide",
      maxDiffPixelRatio: 0.001,
    });
    await expectNoSeriousAccessibilityViolations(page, "Diagramme hell");
    await page.evaluate(() =>
      document.documentElement.setAttribute("data-theme", "dark"),
    );
    await expect.poll(pixel).not.toBe(light);
    await expectNoSeriousAccessibilityViolations(page, "Diagramme dunkel");
    // The canvas follows its container.
    await page.setViewportSize({ width: 390, height: 844 });
    await expect
      .poll(() => canvases.nth(0).evaluate((canvas) => canvas.clientWidth))
      .toBeLessThan(360);
    expect(await page.locator("style").count()).toBe(0);
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

test("mobile shell shows the area and opens every area in the Mehr sheet", async ({
  browser,
}) => {
  const { context, page, pageErrors } = await createCatalogPage(browser, {
    width: 390,
    height: 844,
  });

  try {
    await expect(page.getByTestId("desktop-sidebar")).toBeHidden();
    await expect(page.getByTestId("topbar-zone")).toHaveText("System");
    await expect(
      page.getByRole("navigation", { name: "Hauptnavigation mobil" }),
    ).toBeVisible();

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
    const sheet = page.getByRole("dialog", { name: "Alle Bereiche" });
    await expect(sheet).toBeVisible();
    await expect(sheet.locator('[data-nav-key="system"]')).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expect(sheet.getByText("System-Admin")).toBeVisible();
    await expect(sheet.getByRole("button", { name: "Abmelden" })).toBeVisible();
    await page.screenshot({
      path: `${artifactDirectory}/ui-system-mobile-sheet.png`,
      fullPage: false,
    });
    await expectNoSeriousAccessibilityViolations(page, "Mobile Navigation");
    await page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();
    await expect(page.getByTestId("mobile-menu")).toBeFocused();

    expect(pageErrors).toEqual([]);
  } finally {
    await context.close();
  }
});

/** The zone colour as the shell resolves it, through a CSSOM probe. */
async function zoneColours(page) {
  return page.evaluate(() => {
    const shell = document.querySelector(".shell");
    const probe = document.createElement("span");
    probe.style.setProperty("background-color", "var(--zone)");
    shell.append(probe);
    const zone = getComputedStyle(probe).backgroundColor;
    probe.remove();
    const band = getComputedStyle(
      document.querySelector(".topbar"),
      "::before",
    );
    return { zone, band: band.backgroundColor, bandHeight: band.height };
  });
}

async function expectNoHorizontalOverflow(page, label) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow, label).toBeLessThanOrEqual(1);
}

test("rail shell: g navigation, zone band, skip link and narrow layouts", async ({
  browser,
}) => {
  const { context, page, pageErrors } = await createCatalogPage(browser, {
    width: 1440,
    height: 900,
  });

  try {
    // Only what the server returned: Simone has no orders or invoices.
    const rail = page.getByRole("navigation", { name: "Hauptnavigation" });
    await expect(rail.locator('[data-nav-key="system"]')).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expect(rail.locator('[data-nav-key="orders"]')).toHaveCount(0);
    // Club name from LEONAID_CLUB_NAME (test stacks use the sample name).
    await expect(page.locator(".rail-brand .brand-club")).toHaveText(
      "Lions Club Musterstadt",
    );
    // Cross-surface link into the PWA, with its own zone.
    await expect(
      rail.locator('[data-nav-key="acquisition-app"]'),
    ).toHaveAttribute("href", "/app/");
    await expect(
      rail.locator('[data-nav-key="acquisition-app"]'),
    ).toHaveAttribute("data-zone", "acquisition-app");
    const systemZone = await zoneColours(page);
    expect(systemZone.band).toBe(systemZone.zone);
    expect(systemZone.bandHeight).toBe("3px");

    // Skip link first in tab order, then into the rail.
    await page.keyboard.press("Tab");
    await expect(
      page.getByRole("link", { name: "Zum Inhalt springen" }),
    ).toBeFocused();

    // "g m" goes to the members zone and recolours the band.
    await page.keyboard.press("g");
    await expect(page.locator(".prefix-hint")).toContainText("gedrückt");
    await page.keyboard.press("m");
    await page.waitForURL(`${baseUrl}/admin/members`);
    await expect(page.getByTestId("rail-shell")).toHaveAttribute(
      "data-zone",
      "members",
    );
    await expect(page.getByTestId("topbar-zone")).toHaveText("Mitglieder");
    const membersZone = await zoneColours(page);
    expect(membersZone.band).toBe(membersZone.zone);
    expect(membersZone.band).not.toBe(systemZone.band);

    // Every g binding of the help points at an entry the rail shows.
    await page.keyboard.press("?");
    const help = page.getByRole("dialog", { name: "Tastenkürzel" });
    await expect(help).toBeVisible();
    const goTo = help.locator("section", { hasText: "Gehe zu" }).locator("li");
    const railLinks = await rail.locator("a[data-nav-key]").count();
    const lettered = await rail.locator("a[data-nav-key] .kbd-group").count();
    expect(await goTo.count()).toBe(lettered);
    expect(lettered).toBeGreaterThan(0);
    expect(lettered).toBeLessThanOrEqual(railLinks);
    await page.keyboard.press("Escape");

    // 200 % zoom on 1280 px: 640 CSS px. The rail gives way, nothing overflows.
    await page.setViewportSize({ width: 640, height: 400 });
    await expect(page.getByTestId("desktop-sidebar")).toBeHidden();
    await expect(
      page.getByRole("navigation", { name: "Hauptnavigation mobil" }),
    ).toBeVisible();
    await expectNoHorizontalOverflow(page, "200 % Zoom bei 1280 px");

    // 1024 px: collapsed icon rail without overflow.
    await page.setViewportSize({ width: 1024, height: 768 });
    expect(
      (await page.getByTestId("desktop-sidebar").boundingBox()).width,
    ).toBe(72);
    await expectNoHorizontalOverflow(page, "1024 px");

    // 390 px: bottom nav with 44 px targets, no overflow.
    await page.setViewportSize({ width: 390, height: 844 });
    await expectNoHorizontalOverflow(page, "390 px");
    for (const item of await page
      .getByRole("navigation", { name: "Hauptnavigation mobil" })
      .locator(".nav-item")
      .all()) {
      const box = await item.boundingBox();
      expect(box.height).toBeGreaterThanOrEqual(44);
    }

    expect(pageErrors).toEqual([]);
  } finally {
    await context.close();
  }
});
