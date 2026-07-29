import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const simoneSession = process.env.SIMONE_SESSION;
const correlationId = "poc114-browser-correlation";

if (!baseUrl || !artifactDirectory || !simoneSession) {
  throw new Error("POC-114 Browserumgebung ist unvollständig");
}

test.setTimeout(90_000);

test("System-Admin erkennt Ausfälle und wiederholt echten Mail-Job", async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: { "X-Request-ID": correlationId },
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: simoneSession,
      url: baseUrl,
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
    },
  ]);
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  try {
    await page.goto(`${baseUrl}/admin/system`);
    await expect(
      page.getByRole("heading", { name: "System & Betrieb" }),
    ).toBeVisible();
    await expect(page.getByTestId("operations-panel")).toBeVisible();
    await expect(page.locator("code")).toContainText(correlationId);

    for (const dependency of ["twenty", "rustfs", "mail", "worker"]) {
      await expect(
        page.locator(`[data-dependency="${dependency}"]`),
      ).toContainText("Bereit");
    }

    const retryButton = page.getByRole("button", {
      name: "Sicher wiederholen",
    });
    await expect(retryButton).toHaveCount(1);
    await page.screenshot({
      path: `${artifactDirectory}/operations-dead-letter.png`,
      fullPage: true,
    });

    await retryButton.click();
    await expect(page.getByTestId("operations-no-jobs")).toBeVisible();
    await expect(page.getByText("Keine fehlgeschlagenen Jobs")).toBeVisible();
    await page.screenshot({
      path: `${artifactDirectory}/operations-recovered.png`,
      fullPage: true,
    });

    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByTestId("operations-panel")).toBeVisible();
    await page.screenshot({
      path: `${artifactDirectory}/operations-mobile.png`,
      fullPage: true,
    });

    const accessibility = await new AxeBuilder({ page }).analyze();
    expect(
      accessibility.violations.filter(
        (violation) =>
          violation.impact === "critical" || violation.impact === "serious",
      ),
    ).toEqual([]);
    expect(pageErrors).toEqual([]);
  } finally {
    await context.close();
  }
});
