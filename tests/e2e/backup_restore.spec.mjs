import { analyzeAccessibility } from "./axe.mjs";
import { expect, test } from "./csp-guard.mjs";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const klaraSession = process.env.KLARA_SESSION;
const actionId = "20000000-0000-4000-8000-000000000001";

if (!baseUrl || !artifactDirectory || !klaraSession) {
  throw new Error("POC-112 browser environment is incomplete");
}

test.setTimeout(90_000);

test("restored instance works with an existing session", async ({
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
      page.getByRole("heading", {
        level: 1,
        name: /^Guten (Morgen|Tag|Abend), Klara$/,
      }),
    ).toBeVisible();
    await expect(page.getByTestId("goal-status")).toContainText(
      "90 % erreicht",
    );
    await expect(page.getByTestId("admin-dashboard-metrics")).toContainText(
      "25 Boxen · 600 Stück",
    );
    await expect(page.getByTestId("admin-dashboard-metrics")).toContainText(
      "504,00 €",
    );
    const accessibility = await analyzeAccessibility(page);
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
