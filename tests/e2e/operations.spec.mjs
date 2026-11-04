import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./csp-guard.mjs";
import { readFile } from "node:fs/promises";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const simoneSession = process.env.SIMONE_SESSION;
const correlationId = "poc114-browser-correlation";

if (!baseUrl || !artifactDirectory || !simoneSession) {
  throw new Error("POC-114 browser environment is incomplete");
}

test.setTimeout(90_000);

test("system admin detects outages and retries a real mail job", async ({
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
      page.getByRole("heading", { level: 1, name: "System" }),
    ).toBeVisible();
    await expect(page.getByRole("tab", { name: "Betrieb" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByTestId("operations-panel")).toBeVisible();
    await expect(
      page.getByTestId("operations-panel").locator("code"),
    ).toContainText(correlationId);
    await expect(page.getByTestId("monitoring-summary")).toContainText(
      "Nicht aktiv",
    );
    await expect(page.getByTestId("monitoring-summary")).toContainText(
      "optionale Monitoring-Profil",
    );

    for (const dependency of ["twenty", "rustfs", "mail", "worker"]) {
      await expect(
        page.locator(`[data-dependency="${dependency}"]`),
      ).toContainText("Bereit");
    }

    const dailyReport = page.getByTestId("pilot-daily-report");
    await expect(dailyReport).toBeVisible();
    await dailyReport
      .getByRole("button", { name: "Tagesreport erstellen" })
      .click();
    const dailyResult = dailyReport.getByTestId("pilot-daily-report-result");
    await expect(dailyResult).toContainText("Pilot technisch nicht freigeben");
    await expect(dailyResult).toContainText("4/4 Dienste");
    await expect(dailyResult).toContainText("Pilot-Monitoring ist nicht aktiv");
    await expect(dailyResult).toContainText("Nächster Schritt");
    await expect(dailyResult).not.toContainText("klara.kern@");
    await expect(dailyResult).not.toContainText("Payload");

    const downloadPromise = page.waitForEvent("download");
    await dailyResult
      .getByRole("button", { name: "JSON herunterladen" })
      .click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(
      /^leonaid-pilot-daily-\d{4}-\d{2}-\d{2}\.json$/,
    );
    const downloadPath = await download.path();
    expect(downloadPath).not.toBeNull();
    const downloadedReport = JSON.parse(
      await readFile(downloadPath, { encoding: "utf8" }),
    );
    expect(downloadedReport.schemaVersion).toBe(
      "leonaid.pilot.daily-report/v1",
    );
    expect(downloadedReport.scope).toBe("technical-daily-check");
    expect(downloadedReport.technicalStatus).toBe("blocked");
    expect(JSON.stringify(downloadedReport)).not.toContain("klara.kern@");

    const supportPanel = page.getByTestId("support-diagnostics");
    await expect(supportPanel).toBeVisible();
    await supportPanel
      .getByRole("button", { name: "Diagnose-Test starten" })
      .click();
    await expect(
      supportPanel.getByText("Kontrollierter Fehler wurde erzeugt."),
    ).toBeVisible();
    await expect(supportPanel.getByLabel("Support-Code")).toHaveValue(
      correlationId,
    );
    await supportPanel
      .getByRole("button", { name: "Sicher nachschlagen" })
      .click();
    const supportResult = supportPanel.getByTestId("support-diagnostic-result");
    await expect(supportResult).toBeVisible();
    await expect(supportResult).toContainText(
      "Die Anfrage konnte nicht abgeschlossen werden.",
    );
    await expect(supportResult).toContainText(
      "POST /api/v1/admin/support/probe",
    );
    await expect(supportResult).toContainText(
      "HTTP 503 · support_probe_failed",
    );
    await expect(supportResult).not.toContainText("klara.kern@");
    await expect(supportResult).not.toContainText("Cookie");
    await expect(supportResult).not.toContainText("Payload");

    // The dead letter is one click away: the Betrieb callout opens the
    // Hintergrundaufgaben tab with its own URL.
    await page
      .getByRole("button", { name: "Betroffene Aufgaben ansehen" })
      .click();
    await expect(page).toHaveURL(/\/admin\/system\/jobs$/);
    await expect(
      page.getByRole("tab", { name: /Hintergrundaufgaben/ }),
    ).toHaveAttribute("aria-selected", "true");
    const jobs = page.getByTestId("operations-jobs");
    const retryButton = jobs.getByRole("button", { name: "Erneut versuchen" });
    await expect(retryButton).toHaveCount(1);
    await page.screenshot({
      path: `${artifactDirectory}/operations-dead-letter.png`,
      fullPage: true,
    });

    await retryButton.click();
    const confirm = page.getByRole("alertdialog", {
      name: "Aufgabe erneut versuchen?",
    });
    await confirm.getByRole("button", { name: "Erneut versuchen" }).click();
    await expect(page.getByTestId("operations-no-jobs")).toBeVisible();
    await expect(
      page.getByText("Keine fehlgeschlagenen Aufgaben"),
    ).toBeVisible();
    await page.screenshot({
      path: `${artifactDirectory}/operations-recovered.png`,
      fullPage: true,
    });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("tab", { name: "Betrieb" }).click();
    await expect(page).toHaveURL(/\/admin\/system$/);
    await expect(page.getByTestId("operations-panel")).toBeVisible();
    await expect(page.getByTestId("pilot-daily-report")).toBeVisible();
    await expect(page.getByTestId("support-diagnostics")).toBeVisible();
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
