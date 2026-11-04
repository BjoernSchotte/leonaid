import AxeBuilder from "@axe-core/playwright";
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
  const accessibility = await new AxeBuilder({ page }).analyze();
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
      page.getByRole("heading", { level: 1, name: "Guten Tag, Anna." }),
    ).toBeVisible();
    await expect(page.getByTestId("dashboard-action")).toHaveValue(actionId);
    await expect(page.getByTestId("goal-status")).toContainText(
      "Aktionsziel: 900,00 € von 1.000,00 € erreicht, 90 Prozent.",
    );
    await expect(
      page.getByRole("progressbar", {
        name: "Fortschritt des Aktionsziels",
      }),
    ).toHaveAttribute(
      "aria-valuetext",
      /^Aktionsziel: 900,00\s€ von 1\.000,00\s€ erreicht, 90 Prozent\.$/,
    );
    await expect(page.getByTestId("dashboard-next-step")).toContainText(
      "Mit offenen Sponsoren weiterarbeiten",
    );
    await expect(page.getByTestId("dashboard-next-step")).toContainText(
      "2 ohne Termin",
    );
    const pipeline = page.getByTestId("dashboard-pipeline");
    await expect(pipeline).toContainText("2 Zuordnungen");
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
      "aria-selected",
      "true",
    );
    await expect(page.getByTestId("sponsor-row")).toHaveCount(2);
    await expect(
      page.getByTestId("sponsor-row").locator('[data-status="open"]'),
    ).toHaveCount(2);
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
