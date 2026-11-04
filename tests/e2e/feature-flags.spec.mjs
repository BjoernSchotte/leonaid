import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./csp-guard.mjs";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const simoneSession = process.env.SIMONE_SESSION;

if (!baseUrl || !artifactDirectory || !simoneSession) {
  throw new Error("POC-096 browser environment is incomplete");
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

/** Toggle a switch and confirm the installation-wide change. */
async function toggle(page, control, confirmLabel) {
  await control.focus();
  await control.press("Space");
  await page
    .getByRole("alertdialog")
    .getByRole("button", { name: confirmLabel })
    .click();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
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

test("system admin controls browser and backend through OpenFeature", async ({
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
    await page.goto(`${baseUrl}/admin/system/flags`);
    await expect(page.getByRole("tab", { name: "Funktionen" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(
      page.getByRole("heading", { name: "Funktionen dieser Installation" }),
    ).toBeVisible();
    await expect(page.getByTestId("preview-notice")).toHaveCount(0);
    await expect(page.getByTestId("feature-system-status")).toHaveCount(0);

    const preview = page.getByTestId("feature-switch-admin.preview_notice");
    const systemStatus = page.getByTestId(
      "feature-switch-admin.system_status_panel",
    );
    await expect(preview).not.toBeChecked();
    await expect(systemStatus).not.toBeChecked();

    // A switch only asks; nothing changes until the change is confirmed.
    await preview.focus();
    await preview.press("Space");
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: "Abbrechen" })
      .click();
    await expect(preview).not.toBeChecked();
    await expect(page.getByTestId("preview-notice")).toHaveCount(0);

    await toggle(page, preview, "Einschalten");
    await expect(preview).toBeChecked();
    await expect(page.getByTestId("preview-notice")).toBeVisible();

    await toggle(page, systemStatus, "Einschalten");
    await expect(systemStatus).toBeChecked();
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
    await toggle(page, reloadedStatus, "Ausschalten");
    await expect(reloadedStatus).not.toBeChecked();
    await expect(page.getByTestId("feature-system-status")).toHaveCount(0);
    const disabledStatus = await page.evaluate(async () => {
      const response = await fetch("/api/v1/admin/system-status");
      return response.status;
    });
    expect(disabledStatus).toBe(404);

    await toggle(page, reloadedStatus, "Einschalten");
    await expect(reloadedStatus).toBeChecked();
    await expect(page.getByTestId("feature-system-status")).toContainText(
      "Betriebsbereit",
    );

    await page.setViewportSize({ width: 390, height: 844 });
    await expect(
      page.getByRole("heading", { name: "Funktionen dieser Installation" }),
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
