import { expect, test } from "@playwright/test";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const phase = process.env.LEONAID_UPGRADE_PHASE;
const klaraSession = process.env.KLARA_SESSION;
const expectedOrderCount = process.env.LEONAID_UPGRADE_EXPECTED_ORDER_COUNT;
const expectedQuantity = process.env.LEONAID_UPGRADE_EXPECTED_QUANTITY;
const expectedInvoiced = process.env.LEONAID_UPGRADE_EXPECTED_INVOICED;
const expectedOutstanding = process.env.LEONAID_UPGRADE_EXPECTED_OUTSTANDING;
const actionId = "20000000-0000-4000-8000-000000000001";

if (
  !baseUrl ||
  !artifactDirectory ||
  !phase ||
  !klaraSession ||
  !expectedOrderCount ||
  !expectedQuantity ||
  !expectedInvoiced ||
  !expectedOutstanding
) {
  throw new Error("POC-113 Browserumgebung ist unvollständig");
}

test("Golden-Dashboard bleibt über die Upgradegrenze fachlich stabil", async ({
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
  try {
    const page = await context.newPage();
    await page.goto(`${baseUrl}/admin/?action=${actionId}`);
    await expect(
      page.getByRole("heading", { level: 1, name: "Was jetzt zählt." }),
    ).toBeVisible();
    await expect(page.getByTestId("goal-status")).toContainText("90 Prozent");
    const metrics = page.getByTestId("admin-dashboard-metrics");
    await expect(metrics).toContainText(
      `Bestellungen${expectedOrderCount}${expectedQuantity}`,
    );
    await expect(metrics).toContainText(expectedQuantity);
    await expect(metrics).toContainText(expectedInvoiced);
    await expect(metrics).toContainText(expectedOutstanding);
    await page.screenshot({
      path: `${artifactDirectory}/upgrade-${phase}.png`,
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});
