import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

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
  throw new Error("POC-101 Browserumgebung ist unvollständig");
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

test("Akquisiteurin arbeitet vom persönlichen Dashboard in die gefilterte Pipeline", async ({
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

test("Charity-Admin prüft aktionsweite Zahlen und offene Rechnungen", async ({
  browser,
}) => {
  const { context, page, pageErrors } = await pageFor(browser, klaraSession, {
    width: 1440,
    height: 1000,
  });
  try {
    await page.goto(`${baseUrl}/admin/?action=${actionId}`);
    await expect(
      page.getByRole("heading", { level: 1, name: "Was jetzt zählt." }),
    ).toBeVisible();
    await expect(page.getByTestId("goal-status")).toContainText("90 Prozent");
    const metrics = page.getByTestId("admin-dashboard-metrics");
    await expect(metrics).toContainText("Bestellungen");
    await expect(metrics).toContainText("6");
    await expect(metrics).toContainText("25 Boxen · 600 Stück");
    await expect(metrics).toContainText("900,00 €");
    await expect(metrics).toContainText("504,00 €");
    await expect(metrics).toContainText("360,00 €");
    await expect(page.getByTestId("dashboard-pipeline")).toContainText(
      "5 Zuordnungen",
    );
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

    await metrics.getByRole("link", { name: /Offene Posten/ }).click();
    await expect(page).toHaveURL(/\/admin\/invoices\?.*status=open/);
    await expect(page.getByTestId("invoice-filter-open")).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByTestId("invoice-row")).toHaveCount(1);

    await page.goto(`${baseUrl}/admin/?action=${actionId}`);
    const openPipeline = page
      .getByTestId("dashboard-pipeline")
      .getByRole("link", { name: /Offen 5/ });
    await openPipeline.click();
    await expect(page).toHaveURL(/\/admin\/acquisition\?.*status=open/);
    await expect(
      page.getByTestId("admin-pipeline-filter-open"),
    ).toHaveAttribute("aria-selected", "true");
    await expect(
      page.getByTestId("acquisition-admin-list").locator("tbody tr"),
    ).toHaveCount(5, { timeout: 75_000 });
    expectNoUnexpectedPageErrors(pageErrors);
  } finally {
    await context.close();
  }
});

test("Teilkonfigurierte leere Aktion erklärt den Zustand ohne leere Grafik", async ({
  browser,
}) => {
  const { context, page, pageErrors } = await pageFor(browser, felixSession, {
    width: 1280,
    height: 900,
  });
  try {
    await page.goto(`${baseUrl}/admin/?action=${emptyActionId}`);
    await expect(page.getByTestId("dashboard-action")).toHaveValue(
      emptyActionId,
    );
    await expect(page.getByTestId("dashboard-goal")).toHaveAttribute(
      "data-configured",
      "false",
    );
    await expect(page.getByTestId("goal-status")).toContainText(
      "Ein Zielwert ist noch nicht vollständig gepflegt.",
    );
    await expect(page.getByRole("progressbar")).toHaveCount(0);
    await expect(
      page.getByRole("heading", { name: "Die Pipeline ist noch leer" }),
    ).toBeVisible();
    await expect(page.getByTestId("admin-dashboard-metrics")).toContainText(
      "0",
    );
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
