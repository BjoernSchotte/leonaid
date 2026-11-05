import { analyzeAccessibility, WCAG_TAGS } from "./axe.mjs";
import { expect, test } from "./csp-guard.mjs";
import { invoiceRows } from "./invoice-list.mjs";
import { writeFile } from "node:fs/promises";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const annaSession = process.env.ANNA_SESSION;
const klaraSession = process.env.KLARA_SESSION;
const actionId = "20000000-0000-4000-8000-000000000001";

if (!baseUrl || !artifactDirectory || !annaSession || !klaraSession) {
  throw new Error("POC-102 browser environment is incomplete");
}

test.setTimeout(120_000);

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

async function contextFor(browser, session, viewport) {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport,
  });
  if (session) await context.addCookies([sessionCookie(session)]);
  await context.addInitScript(() => {
    window.localStorage.setItem("leonaid.theme", "light");
    window.localStorage.setItem("leonaid.sidebar-collapsed", "false");
  });
  return context;
}

async function expectNoSeriousAxeFindings(page, label) {
  const results = await analyzeAccessibility(page, { tags: WCAG_TAGS });
  const severe = results.violations.filter(({ impact }) =>
    ["critical", "serious"].includes(impact),
  );
  expect(
    severe,
    `${label}: ${severe
      .map(
        (violation) =>
          `${violation.id}: ${violation.help} (${violation.nodes.length})`,
      )
      .join("\n")}`,
  ).toEqual([]);
  return {
    checkedUrl: page.url(),
    criticalOrSerious: severe.length,
    label,
    totalViolations: results.violations.length,
  };
}

async function expectNoHorizontalOverflow(page, label) {
  const result = await page.evaluate(() => ({
    overflow: document.documentElement.scrollWidth - window.innerWidth,
    viewportWidth: window.innerWidth,
  }));
  expect(
    result.overflow,
    `${label}: ${JSON.stringify(result)}`,
  ).toBeLessThanOrEqual(1);
}

async function expectTouchTarget(locator, label) {
  const box = await locator.boundingBox();
  expect(box, `${label} is not visible`).not.toBeNull();
  expect(
    box.height,
    `${label} ist niedriger als 44 Pixel`,
  ).toBeGreaterThanOrEqual(44);
  expect(
    box.width,
    `${label} ist schmaler als 44 Pixel`,
  ).toBeGreaterThanOrEqual(44);
}

function collectPageErrors(page) {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

function expectNoUnexpectedPageErrors(errors) {
  expect(
    errors.filter(
      (message) =>
        !message.includes("Failed to register a ServiceWorker") &&
        !message.includes("An SSL certificate error occurred"),
    ),
  ).toEqual([]);
}

test("charity admin completes the desktop review path without losing context", async ({
  browser,
}) => {
  const context = await contextFor(browser, klaraSession, {
    width: 1440,
    height: 1000,
  });
  const page = await context.newPage();
  const pageErrors = collectPageErrors(page);
  try {
    await page.goto(`${baseUrl}/admin/?action=${actionId}`);
    await expect(
      page.getByRole("heading", {
        level: 1,
        name: /^Guten (Morgen|Tag|Abend), Klara$/,
      }),
    ).toBeVisible();
    await expect(page.getByTestId("goal-status")).toContainText(
      "90 % erreicht",
    );
    await expect(page.getByTestId("current-action")).toHaveText(
      "Krapfentaxi 2026",
    );

    await page.keyboard.press("Tab");
    await expect(
      page.getByRole("link", { name: "Zum Inhalt springen" }),
    ).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("#main-content")).toBeFocused();

    // Keyboard walkthrough: palette → Aufgaben → back.
    await page.keyboard.press("Control+k");
    const palette = page.getByRole("dialog", { name: "Befehlspalette" });
    await expect(palette.getByRole("combobox")).toBeFocused();
    await page.keyboard.type("Gehe zu Aufg");
    await expect(
      palette.locator("[cmdk-item][data-selected='true'] .palette-label"),
    ).toHaveText("Aufgaben");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/admin\/tasks(?:[/?]|$)/);
    await page.goBack();
    await expect(page).toHaveURL(new RegExp(`/admin/\\?action=${actionId}`));
    await expect(
      page.getByRole("heading", {
        level: 1,
        name: /^Guten (Morgen|Tag|Abend), Klara$/,
      }),
    ).toBeVisible();

    await page.locator("summary", { hasText: "Weitere Kennzahlen" }).click();
    const metrics = page.getByTestId("admin-dashboard-metrics");
    await metrics.getByRole("link", { name: /Offene Posten/ }).click();
    // The dashboard's ?status=open link lands in the "Offen" list view.
    await expect(page).toHaveURL(/\/admin\/invoices\?action=/);
    await expect(page).not.toHaveURL(/status=/);
    await expect(
      page
        .getByRole("navigation", { name: "Gespeicherte Ansichten" })
        .getByRole("button", { name: "Offen", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(invoiceRows(page)).toHaveCount(1);
    await expect(
      page.getByRole("heading", { level: 1, name: "Rechnungen" }),
    ).toBeVisible();
    await expect(page.locator("main")).not.toContainText(
      /Twenty|PostgreSQL|UUID|API-Endpunkt/,
    );

    await page.evaluate(() => {
      document.documentElement.style.fontSize = "32px";
    });
    await expectNoHorizontalOverflow(page, "Admin-Rechnungen bei 200 % Text");
    const accessibility = await expectNoSeriousAxeFindings(
      page,
      "Charity-Admin Desktop",
    );
    await page.screenshot({
      path: `${artifactDirectory}/ux-admin-desktop.png`,
      fullPage: true,
    });
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "";
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    await expect(
      page.getByRole("heading", { level: 1, name: "Rechnungen" }),
    ).toBeVisible();
    await expect(page.getByTestId("mobile-menu")).toBeVisible();
    await expectNoHorizontalOverflow(page, "Charity-Admin Smartphone");
    await writeFile(
      `${artifactDirectory}/ux-admin-accessibility.json`,
      `${JSON.stringify(accessibility, null, 2)}\n`,
    );
    expectNoUnexpectedPageErrors(pageErrors);
  } finally {
    await context.close();
  }
});

const previousActionId = "20000000-0000-4000-8000-000000000002";

test("charity admin keeps the chosen campaign across pages and widths", async ({
  browser,
}) => {
  const context = await contextFor(browser, klaraSession, {
    width: 1440,
    height: 1000,
  });
  const page = await context.newPage();
  const pageErrors = collectPageErrors(page);
  const switcherMenu = page.getByRole("dialog", { name: "Aktion wechseln" });
  try {
    await page.goto(`${baseUrl}/admin/?action=${actionId}`);
    const current = page.getByTestId("current-action");
    await expect(current).toHaveText("Krapfentaxi 2026");

    // Rail switcher: the dashboard reloads with the other campaign.
    await page.getByTestId("campaign-switcher").click();
    await switcherMenu
      .getByRole("option", { name: /Krapfentaxi 2025/ })
      .click();
    await page.waitForURL(`${baseUrl}/admin/?action=${previousActionId}`);
    await expect(current).toHaveText("Krapfentaxi 2025");

    // Rail links carry the choice into campaign-scoped pages.
    const rail = page.getByRole("navigation", { name: "Hauptnavigation" });
    await rail.locator('[data-nav-key="orders"]').click();
    await page.waitForURL(
      /\/admin\/orders\?action=20000000-0000-4000-8000-000000000002$/,
    );
    await expect(current).toHaveText("Krapfentaxi 2025");
    // A page that ignores the campaign keeps it in the rail.
    await rail.locator('[data-nav-key="members"]').click();
    await page.waitForURL(`${baseUrl}/admin/members`);
    await expect(current).toHaveText("Krapfentaxi 2025");
    // Typed URL without ?action=: the tab's choice still applies.
    await page.goto(`${baseUrl}/admin/invoices`);
    await expect(page.getByTestId("invoice-action")).toHaveValue(
      previousActionId,
    );
    await expect(page).toHaveURL(/action=20000000-0000-4000-8000-000000000002/);
    await expect(current).toHaveText("Krapfentaxi 2025");

    // Palette command: the rail switcher opens with focus in its search.
    await page.keyboard.press("Control+k");
    const palette = page.getByRole("dialog", { name: "Befehlspalette" });
    await palette.getByRole("combobox").fill("Aktion wechseln");
    await palette.getByRole("option", { name: /Aktion wechseln/ }).click();
    await expect(switcherMenu).toBeVisible();
    await expect(switcherMenu.getByRole("combobox")).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(switcherMenu).toHaveCount(0);

    // 1024 px: the collapsed rail keeps a compact switcher.
    await page.setViewportSize({ width: 1024, height: 900 });
    await expect(page.getByTestId("campaign-switcher")).toBeHidden();
    await page.getByTestId("campaign-switcher-compact").click();
    await switcherMenu
      .getByRole("option", { name: /Krapfentaxi 2026/ })
      .click();
    await page.waitForURL(
      /\/admin\/invoices\?action=20000000-0000-4000-8000-000000000001$/,
    );
    await expect(page.getByTestId("invoice-action")).toHaveValue(actionId);

    // 390 px: the "Mehr" sheet has the switcher and hands off to the palette.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByTestId("mobile-menu").click();
    const sheet = page.getByRole("dialog", { name: "Alle Bereiche" });
    await expect(sheet).toBeVisible();
    await sheet.locator(".sheet-campaign").click();
    await expect(
      sheet.getByRole("dialog", { name: "Aktion wechseln" }),
    ).toBeVisible();
    await page.keyboard.press("Escape");
    await sheet.getByRole("button", { name: "Suchen und Befehle" }).click();
    await expect(sheet).toBeHidden();
    await expect(palette.getByRole("combobox")).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("mobile-menu")).toBeFocused();
    await expectNoHorizontalOverflow(page, "Kampagnenwahl Smartphone");

    // Growing past 720 px closes an open sheet.
    await page.getByTestId("mobile-menu").click();
    await expect(sheet).toBeVisible();
    await page.setViewportSize({ width: 1024, height: 900 });
    await expect(sheet).toBeHidden();
    expectNoUnexpectedPageErrors(pageErrors);
  } finally {
    await context.close();
  }
});

test("acquirer reaches sponsor and order capture on mobile with clear guidance", async ({
  browser,
}) => {
  const context = await contextFor(browser, annaSession, {
    width: 390,
    height: 844,
  });
  const page = await context.newPage();
  const pageErrors = collectPageErrors(page);
  try {
    await page.goto(`${baseUrl}/app/?action=${actionId}`);
    await expect(
      page.getByRole("heading", {
        level: 1,
        name: /^Guten (Morgen|Tag|Abend), Anna\.$/,
      }),
    ).toBeVisible();
    await expect(page.getByTestId("goal-status")).toHaveText(
      /^Aktionsziel: 900,00\s€ von 1\.000,00\s€ erreicht, 90 Prozent\.$/,
    );
    await expect(
      page.getByRole("meter", { name: "Fortschritt des Aktionsziels" }),
    ).toBeVisible();
    // Prototype Start: the pipeline leads into the filtered sponsor list.
    const openStage = page
      .getByTestId("dashboard-pipeline")
      .getByRole("link", { name: /Offen 2/ });
    await expectTouchTarget(openStage, "Pipeline-Stufe Offen");
    await openStage.click();
    await expect(page).toHaveURL(/\/app\/sponsors\?.*status=open/);
    await expect(page.getByTestId("sponsor-row")).toHaveCount(2);

    const musterwerk = page
      .getByTestId("sponsor-row")
      .filter({ hasText: "Musterwerk GmbH" });
    await expect(musterwerk).toHaveCount(1);
    await expectTouchTarget(musterwerk, "Sponsor öffnen");
    await musterwerk.click();
    const capture = page.getByTestId("order-open");
    await expectTouchTarget(capture, "Bestellung aus Sponsor-Kontext");
    await capture.click();
    await expect(
      page.getByRole("heading", {
        level: 1,
        name: "Bestellung für Musterwerk GmbH",
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("group", { name: "Anzahl Boxen" }),
    ).toBeVisible();
    await expect(page.getByTestId("commitment-preview-total")).toHaveText(
      "Summe 36,00 €",
    );
    await expect(page.locator("main")).not.toContainText(
      /Twenty|PostgreSQL|UUID|API-Endpunkt|Datensatz-ID/,
    );
    await expectTouchTarget(
      page.getByRole("button", { name: "Weiter" }),
      "Weiter zur Lieferung",
    );
    await expectNoHorizontalOverflow(page, "Mobile Bestellerfassung");
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "32px";
    });
    await expectNoHorizontalOverflow(
      page,
      "Mobile Bestellerfassung bei 200 % Text",
    );
    const accessibility = await expectNoSeriousAxeFindings(
      page,
      "Akquisiteurin Smartphone",
    );
    await page.screenshot({
      path: `${artifactDirectory}/ux-acquirer-mobile.png`,
      fullPage: true,
    });
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "";
    });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.reload();
    await expect(
      page.getByRole("heading", {
        level: 1,
        name: "Bestellung für Musterwerk GmbH",
      }),
    ).toBeVisible();
    await expectNoHorizontalOverflow(page, "Akquisiteurin Desktop");
    await writeFile(
      `${artifactDirectory}/ux-acquirer-accessibility.json`,
      `${JSON.stringify(accessibility, null, 2)}\n`,
    );
    expectNoUnexpectedPageErrors(pageErrors);
  } finally {
    await context.close();
  }
});

test("public customer understands form, validation and next step", async ({
  browser,
}) => {
  const context = await contextFor(browser, undefined, {
    width: 390,
    height: 844,
  });
  const page = await context.newPage();
  const pageErrors = collectPageErrors(page);
  try {
    await page.goto(`${baseUrl}/krapfentaxi`, { waitUntil: "networkidle" });
    await expect(
      page.getByRole("heading", { level: 1, name: "Krapfentaxi 2026" }),
    ).toBeVisible();
    await page.getByRole("link", { name: "Jetzt bestellen" }).click();
    const form = page.locator("[data-order-form]");
    await expect(form).toBeVisible();
    await expect(form.getByText("Menge und Bestellwert")).toBeVisible();
    await expect(
      form.getByText("Eine bestehende Firma wird automatisch erkannt."),
    ).toBeVisible();
    await expect(
      form.getByText("Grundlage für die spätere Routenzuordnung."),
    ).toBeVisible();
    await expect(page.locator("main")).not.toContainText(
      /Twenty|PostgreSQL|UUID|API-Endpunkt|Datensatz-ID/,
    );

    const company = form.locator('input[name="companyName"]');
    await company.fill("UX Prüfatelier GmbH");
    await form.locator('button[type="submit"]').click();
    // The error summary takes the focus and links each field.
    const summary = form.locator("[data-form-message]");
    await expect(summary).toBeFocused();
    await expect(company).toHaveValue("UX Prüfatelier GmbH");
    await expect(summary).toContainText("Bitte prüfen Sie");
    await expect(summary).toContainText(
      "Die Bestellung wurde noch nicht gesendet. Ihre Eingaben bleiben erhalten.",
    );
    await summary.getByRole("link", { name: /^Vorname:/ }).click();
    await expect(form.locator('input[name="givenName"]')).toBeFocused();
    await expectTouchTarget(
      form.locator('button[type="submit"]'),
      "Öffentliche Bestellung absenden",
    );
    await expectNoHorizontalOverflow(page, "Öffentliches Bestellformular");
    const accessibility = await expectNoSeriousAxeFindings(
      page,
      "Öffentlicher Besteller Smartphone",
    );
    await page.screenshot({
      path: `${artifactDirectory}/ux-public-order-mobile.png`,
      fullPage: true,
    });
    await writeFile(
      `${artifactDirectory}/ux-public-accessibility.json`,
      `${JSON.stringify(accessibility, null, 2)}\n`,
    );
    expectNoUnexpectedPageErrors(pageErrors);
  } finally {
    await context.close();
  }
});

async function measureCorePage(browser, scenario) {
  const context = await contextFor(browser, scenario.session, {
    width: 390,
    height: 844,
  });
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.emulateNetworkConditions", {
    connectionType: "cellular4g",
    downloadThroughput: (10 * 1024 * 1024) / 8,
    latency: 40,
    offline: false,
    uploadThroughput: (5 * 1024 * 1024) / 8,
  });
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  await cdp.send("Performance.enable");
  await page.addInitScript(() => {
    window.__leonaidVitals = { cls: 0, lcp: 0 };
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        window.__leonaidVitals.lcp = Math.max(
          window.__leonaidVitals.lcp,
          entry.startTime,
        );
      }
    }).observe({ buffered: true, type: "largest-contentful-paint" });
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (!entry.hadRecentInput) window.__leonaidVitals.cls += entry.value;
      }
    }).observe({ buffered: true, type: "layout-shift" });
  });

  try {
    await page.goto(`${baseUrl}${scenario.path}`, { waitUntil: "networkidle" });
    await scenario.ready(page);
    await page.waitForTimeout(250);
    const browserMetrics = await cdp.send("Performance.getMetrics");
    const measured = await page.evaluate(() => {
      const navigation = performance.getEntriesByType("navigation")[0];
      return {
        cls: Number(window.__leonaidVitals.cls.toFixed(4)),
        domContentLoadedMilliseconds: Math.round(
          navigation.domContentLoadedEventEnd,
        ),
        lcpMilliseconds: Math.round(window.__leonaidVitals.lcp),
        transferredBytes: Math.round(
          performance
            .getEntriesByType("resource")
            .reduce((total, entry) => total + (entry.transferSize || 0), 0),
        ),
      };
    });
    const taskDuration = browserMetrics.metrics.find(
      ({ name }) => name === "TaskDuration",
    )?.value;
    const result = {
      ...measured,
      mainThreadTaskMilliseconds: Math.round((taskDuration ?? 0) * 1000),
      route: scenario.path,
    };
    expect(result.lcpMilliseconds, scenario.label).toBeGreaterThan(0);
    expect(result.lcpMilliseconds, scenario.label).toBeLessThanOrEqual(2500);
    expect(result.cls, scenario.label).toBeLessThanOrEqual(0.1);
    expect(
      result.domContentLoadedMilliseconds,
      scenario.label,
    ).toBeLessThanOrEqual(2500);
    expect(result.transferredBytes, scenario.label).toBeLessThanOrEqual(
      1_000_000,
    );
    expect(
      result.mainThreadTaskMilliseconds,
      scenario.label,
    ).toBeLessThanOrEqual(1800);
    return result;
  } finally {
    await context.close();
  }
}

test("three core surfaces meet reproducible mobile performance budgets", async ({
  browser,
}) => {
  const scenarios = [
    {
      label: "Öffentliche Aktionsseite",
      path: "/krapfentaxi",
      ready: (page) =>
        page
          .getByRole("heading", { level: 1, name: "Krapfentaxi 2026" })
          .waitFor(),
    },
    {
      label: "Akquisiteur-Dashboard",
      path: `/app/?action=${actionId}`,
      ready: (page) =>
        page
          .getByRole("heading", {
            level: 1,
            name: /^Guten (Morgen|Tag|Abend), Anna\.$/,
          })
          .waitFor(),
      session: annaSession,
    },
    {
      label: "Charity-Admin-Dashboard",
      path: `/admin/?action=${actionId}`,
      ready: (page) =>
        page
          .getByRole("heading", {
            level: 1,
            name: /^Guten (Morgen|Tag|Abend), Klara$/,
          })
          .waitFor(),
      session: klaraSession,
    },
  ];
  const measured = [];
  for (const scenario of scenarios) {
    measured.push(await measureCorePage(browser, scenario));
  }
  await writeFile(
    `${artifactDirectory}/performance-report.json`,
    `${JSON.stringify(
      {
        budgets: {
          cls: 0.1,
          domContentLoadedMilliseconds: 2500,
          lcpMilliseconds: 2500,
          mainThreadTaskMilliseconds: 1800,
          transferredBytes: 1_000_000,
        },
        measured,
        profile: {
          browser: "Chromium via Playwright 1.64.1",
          cpuThrottlingRate: 4,
          network: {
            downloadMbps: 10,
            latencyMilliseconds: 40,
            uploadMbps: 5,
          },
          viewport: "390x844",
        },
      },
      null,
      2,
    )}\n`,
  );
});
