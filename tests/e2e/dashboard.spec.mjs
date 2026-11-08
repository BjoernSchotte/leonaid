import { analyzeAccessibility } from "./axe.mjs";
import { expect, test } from "./csp-guard.mjs";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const annaSession = process.env.ANNA_SESSION;
const klaraSession = process.env.KLARA_SESSION;
const felixSession = process.env.FELIX_SESSION;
const actionId = "20000000-0000-4000-8000-000000000001";
const emptyActionId = "20000000-0000-4000-8000-000000000003";

if (
  !baseUrl ||
  !artifactDirectory ||
  !annaSession ||
  !klaraSession ||
  !felixSession
) {
  throw new Error("POC-101 browser environment is incomplete");
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

async function pageFor(browser, session, viewport) {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport,
  });
  await context.addCookies([sessionCookie(session)]);
  await context.addInitScript(() => {
    window.localStorage.setItem("leonaid.theme", "light");
    window.localStorage.setItem("leonaid.sidebar-collapsed", "false");
  });
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  return { context, page, pageErrors };
}

function expectNoUnexpectedPageErrors(pageErrors) {
  expect(
    pageErrors.filter(
      (message) =>
        !message.includes("Failed to register a ServiceWorker") ||
        !message.includes("An SSL certificate error occurred"),
    ),
  ).toEqual([]);
}

async function expectNoSeriousAccessibilityViolations(page, label) {
  const accessibility = await analyzeAccessibility(page);
  expect(
    accessibility.violations.filter(
      (violation) =>
        violation.impact === "critical" || violation.impact === "serious",
    ),
    label,
  ).toEqual([]);
}

test("acquirer works from the personal dashboard into the filtered pipeline", async ({
  browser,
}) => {
  const { context, page, pageErrors } = await pageFor(browser, annaSession, {
    width: 390,
    height: 844,
  });
  try {
    await page.goto(`${baseUrl}/app/?action=${actionId}`);
    await expect(
      page.getByRole("heading", {
        level: 1,
        name: /^Guten (Morgen|Tag|Abend), Anna\.$/,
      }),
    ).toBeVisible();
    // One campaign: no picker; the app bar names it (prototype Start).
    await expect(page.getByTestId("acquirer-action")).toHaveCount(0);
    await expect(page.getByTestId("goal-status")).toContainText(
      "Aktionsziel: 900,00 € von 1.000,00 € erreicht, 90 Prozent.",
    );
    const goal = page.getByTestId("dashboard-goal");
    await expect(
      goal.getByRole("heading", { name: "Gemeinsames Ziel" }),
    ).toBeVisible();
    await expect(
      goal.getByRole("meter", { name: "Fortschritt des Aktionsziels" }),
    ).toHaveAttribute("aria-valuenow", "9000");
    await expect(goal).toContainText("Noch 100,00 € bis zum Ziel.");
    // "Heute dran": the follow-ups due today or overdue.
    await expect(
      page.getByRole("heading", { name: "Heute dran" }),
    ).toBeVisible();
    // This stack's sponsors have no follow-up yet (activities/contract.py proves
    // the filled list on its own data).
    await expect(page.getByTestId("due-today")).toHaveCount(0);
    await expect(
      page.getByRole("heading", { name: "Heute ist nichts fällig" }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Alle Wiedervorlagen" }),
    ).toHaveAttribute("href", /\/app\/activities\?view=contacts/);
    const pipeline = page.getByTestId("dashboard-pipeline");
    await expect(
      pipeline.getByRole("heading", { name: "Deine persönliche Pipeline" }),
    ).toBeVisible();
    const open = pipeline.getByRole("link", { name: /Offen 2/ });
    await expect(open).toHaveAttribute("href", /status=open/);

    await page.screenshot({
      path: `${artifactDirectory}/dashboard-acquirer-mobile.png`,
      fullPage: true,
    });
    await expectNoSeriousAccessibilityViolations(page, "Akquisiteur-Dashboard");

    await open.click();
    await expect(page).toHaveURL(/\/app\/sponsors\?.*status=open/);
    await expect(page.getByTestId("sponsor-status-open")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // Handed-over sponsors leave the list, so "Übergeben" is no filter.
    await expect(page.getByTestId("sponsor-status-handed_over")).toHaveCount(0);
    await expect(page.getByTestId("sponsor-row")).toHaveCount(2);
    await expect(page.getByTestId("sponsor-row")).toContainText([
      "Offen",
      "Offen",
    ]);
    expectNoUnexpectedPageErrors(pageErrors);
  } finally {
    await context.close();
  }
});

test("charity admin sees next steps, delivery, goal, weekly value and pipeline", async ({
  browser,
}) => {
  const { context, page, pageErrors } = await pageFor(browser, klaraSession, {
    width: 1440,
    height: 1000,
  });
  try {
    await page.goto(`${baseUrl}/admin/?action=${actionId}`);
    await expect(
      page.getByRole("heading", {
        level: 1,
        name: /^Guten (Morgen|Tag|Abend), Klara$/,
      }),
    ).toBeVisible();
    await expect(page.locator(".page-sub")).toContainText("Krapfentaxi 2026");
    const goal = page.getByTestId("dashboard-goal");
    await expect(goal).toContainText("900,00 €");
    await expect(goal).toContainText("von 1.000,00 €");
    await expect(page.getByTestId("goal-status")).toContainText(
      "90 % erreicht",
    );

    const queue = page.getByTestId("dashboard-queue");
    const review = queue.getByRole("link", { name: /Bestellungen prüfen/ });
    await expect(review).toBeVisible();
    await expect(review).toHaveAttribute("href", /\/admin\/orders\?action=/);
    await expect(page.getByTestId("dashboard-primary-action")).toHaveText(
      /^\d+ Bestellungen prüfen$/,
    );

    const weekly = page.getByTestId("dashboard-weekly");
    await expect(weekly.locator(".spark-bar")).toHaveCount(8);
    await expect(weekly.getByRole("img")).toHaveAttribute(
      "aria-label",
      /^Bestellwert der letzten 8 Wochen, diese Woche /,
    );
    await expect(weekly.locator(".spark-axis")).toContainText(/KW \d+/);

    const pipeline = page.getByTestId("dashboard-pipeline");
    await expect(
      pipeline.getByRole("link", { name: /Offen\s*5/ }),
    ).toBeVisible();
    await expect(
      page.locator("summary", {
        hasText: "So werden die Kennzahlen berechnet",
      }),
    ).toBeVisible();

    await page.screenshot({
      path: `${artifactDirectory}/dashboard-admin-desktop.png`,
      fullPage: true,
    });
    await expectNoSeriousAccessibilityViolations(page, "Admin-Dashboard");

    await review.click();
    await expect(page).toHaveURL(/\/admin\/orders\?action=/);
    await expect(
      page
        .getByRole("navigation", { name: "Gespeicherte Ansichten" })
        .getByRole("button", { name: "Zu prüfen", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");

    await page.goto(`${baseUrl}/admin/?action=${actionId}`);
    await page
      .getByTestId("dashboard-pipeline")
      .getByRole("link", { name: /Offen\s*5/ })
      .click();
    await expect(page).toHaveURL(/\/admin\/acquisition\?.*status=open/);
    await expect(
      page.getByTestId("admin-pipeline-filter-open"),
    ).toHaveAttribute("aria-selected", "true");
    await expect(
      page.getByTestId("acquisition-admin-list").locator("tbody tr"),
    ).toHaveCount(5, { timeout: 75_000 });
    // The status filter is a tab list: one tab stop, arrows move and select.
    const openTab = page.getByTestId("admin-pipeline-filter-open");
    await expect(openTab).toHaveAttribute("tabindex", "0");
    await expect(page.getByTestId("admin-pipeline-filter-all")).toHaveAttribute(
      "tabindex",
      "-1",
    );
    await openTab.focus();
    await page.keyboard.press("ArrowRight");
    const contacted = page.getByTestId("admin-pipeline-filter-contacted");
    await expect(contacted).toBeFocused();
    await expect(contacted).toHaveAttribute("aria-selected", "true");
    await expect(page).toHaveURL(/status=contacted/);
    await page.keyboard.press("ArrowLeft");
    await expect(openTab).toBeFocused();
    await expect(openTab).toHaveAttribute("aria-selected", "true");

    // 390 px: one column, the primary action spans the width.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${baseUrl}/admin/?action=${actionId}`);
    await expect(page.getByTestId("dashboard-queue")).toBeVisible();
    await expectNoSeriousAccessibilityViolations(page, "Admin-Dashboard mobil");
    expectNoUnexpectedPageErrors(pageErrors);
  } finally {
    await context.close();
  }
});

test("partly configured empty action explains its state without an empty chart", async ({
  browser,
}) => {
  const { context, page, pageErrors } = await pageFor(browser, felixSession, {
    width: 1280,
    height: 900,
  });
  try {
    await page.goto(`${baseUrl}/admin/?action=${emptyActionId}`);
    await expect(page.getByTestId("admin-dashboard")).toBeVisible();
    await expect(page.getByTestId("goal-status")).toContainText(
      "Noch kein Zielwert gepflegt",
    );
    await expect(page.getByRole("progressbar")).toHaveCount(0);
    await expect(page.getByTestId("dashboard-queue-empty")).toContainText(
      "Alles erledigt.",
    );
    await expect(page.getByTestId("dashboard-primary-action")).toHaveCount(0);
    await expect(
      page.getByTestId("dashboard-pipeline").locator(".pipeline-count"),
    ).toHaveText(["0", "0", "0", "0", "0"]);
    await page.screenshot({
      path: `${artifactDirectory}/dashboard-empty-desktop.png`,
      fullPage: true,
    });
    await expectNoSeriousAccessibilityViolations(
      page,
      "Teilkonfiguriertes Dashboard",
    );
    expectNoUnexpectedPageErrors(pageErrors);
  } finally {
    await context.close();
  }
});
