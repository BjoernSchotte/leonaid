import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const klaraSession = process.env.KLARA_SESSION;
const actionId = "20000000-0000-4000-8000-000000000001";

if (!baseUrl || !artifactDirectory || !klaraSession) {
  throw new Error("POC-112 Browserumgebung ist unvollständig");
}

test.setTimeout(90_000);

test("wiederhergestellte Instanz ist mit bestehender Sitzung arbeitsfähig", async ({
  browser,
}) => {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1440, height: 1000 },
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: klaraSession,
      url: baseUrl,
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
    },
  ]);
  await context.addInitScript(() => {
    window.localStorage.setItem("leonaid.theme", "light");
    window.localStorage.setItem("leonaid.sidebar-collapsed", "false");
  });
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await page.goto(`${baseUrl}/admin/?action=${actionId}`);
    await expect(
      page.getByRole("heading", { level: 1, name: "Was jetzt zählt." }),
    ).toBeVisible();
    await expect(page.getByTestId("goal-status")).toContainText("90 Prozent");
    await expect(page.getByTestId("admin-dashboard-metrics")).toContainText(
      "25 Boxen · 600 Stück",
    );
    await expect(page.getByTestId("admin-dashboard-metrics")).toContainText(
      "504,00 €",
    );
    const accessibility = await new AxeBuilder({ page }).analyze();
    expect(
      accessibility.violations.filter(
        (violation) =>
          violation.impact === "critical" || violation.impact === "serious",
      ),
    ).toEqual([]);
    expect(pageErrors).toEqual([]);
    await page.screenshot({
      path: `${artifactDirectory}/backup-restored-admin.png`,
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});
