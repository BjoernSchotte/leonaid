import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const simoneSession = process.env.SIMONE_SESSION;

if (!baseUrl || !artifactDirectory || !simoneSession) {
  throw new Error("POC-096 Browserumgebung ist unvollständig");
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

async function expectNoSeriousAccessibilityViolations(page) {
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(
    accessibility.violations.filter(
      (violation) =>
        violation.impact === "critical" || violation.impact === "serious",
    ),
  ).toEqual([]);
}

test("System-Admin steuert Browser und Backend über OpenFeature", async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    ignoreHTTPSErrors: true,
  });
  await context.addCookies([sessionCookie(simoneSession)]);
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  try {
    await page.goto(`${baseUrl}/admin/system`);
    await expect(
      page.getByRole("heading", { name: "Feature-Flags" }),
    ).toBeVisible();
    await expect(page.getByTestId("preview-notice")).toHaveCount(0);
    await expect(page.getByTestId("feature-system-status")).toHaveCount(0);

    const preview = page.getByTestId("feature-switch-admin.preview_notice");
    const systemStatus = page.getByTestId(
      "feature-switch-admin.system_status_panel",
    );
    await expect(preview).toHaveAttribute("aria-checked", "false");
    await expect(systemStatus).toHaveAttribute("aria-checked", "false");

    await preview.focus();
    await preview.press("Space");
    await expect(preview).toHaveAttribute("aria-checked", "true");
    await expect(page.getByTestId("preview-notice")).toBeVisible();

    await systemStatus.focus();
    await systemStatus.press("Space");
    await expect(systemStatus).toHaveAttribute("aria-checked", "true");
    await expect(page.getByTestId("feature-system-status")).toContainText(
      "Betriebsbereit",
    );
    await expect(page.getByTestId("feature-system-status")).toContainText(
      "openfeature",
    );

    await page.reload();
    await expect(page.getByTestId("preview-notice")).toBeVisible();
    await expect(page.getByTestId("feature-system-status")).toContainText(
      "Betriebsbereit",
    );
    await page.screenshot({
      path: `${artifactDirectory}/feature-flags-desktop.png`,
      fullPage: true,
    });

    const reloadedStatus = page.getByTestId(
      "feature-switch-admin.system_status_panel",
    );
    await reloadedStatus.click();
    await expect(reloadedStatus).toHaveAttribute("aria-checked", "false");
    await expect(page.getByTestId("feature-system-status")).toHaveCount(0);
    const disabledStatus = await page.evaluate(async () => {
      const response = await fetch("/api/v1/admin/system-status");
      return response.status;
    });
    expect(disabledStatus).toBe(404);

    await reloadedStatus.click();
    await expect(reloadedStatus).toHaveAttribute("aria-checked", "true");
    await expect(page.getByTestId("feature-system-status")).toContainText(
      "Betriebsbereit",
    );

    await page.setViewportSize({ width: 390, height: 844 });
    await expect(
      page.getByRole("heading", { name: "Feature-Flags" }),
    ).toBeVisible();
    await page.screenshot({
      path: `${artifactDirectory}/feature-flags-mobile.png`,
      fullPage: true,
    });

    await expectNoSeriousAccessibilityViolations(page);
    expect(pageErrors).toEqual([]);
  } finally {
    await context.close();
  }
});
