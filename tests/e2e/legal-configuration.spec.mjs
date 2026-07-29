import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const simoneSession = process.env.SIMONE_SESSION;
const klaraSession = process.env.KLARA_SESSION;

if (!baseUrl || !artifactDirectory || !simoneSession || !klaraSession) {
  throw new Error("PILOT-044 Browserumgebung ist unvollständig");
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

test("zwei System-Admins aktivieren eine rechtliche Grundlage", async ({
  browser,
}) => {
  const klaraContext = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    ignoreHTTPSErrors: true,
  });
  await klaraContext.addCookies([sessionCookie(klaraSession)]);
  const klaraPage = await klaraContext.newPage();
  const pageErrors = [];
  klaraPage.on("pageerror", (error) => pageErrors.push(error.message));

  const simoneContext = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    ignoreHTTPSErrors: true,
  });
  await simoneContext.addCookies([sessionCookie(simoneSession)]);
  const simonePage = await simoneContext.newPage();
  simonePage.on("pageerror", (error) => pageErrors.push(error.message));

  try {
    await klaraPage.goto(`${baseUrl}/admin/legal`);
    await expect(
      klaraPage.getByRole("heading", { name: "Organisation & Recht" }),
    ).toBeVisible();
    await expect(
      klaraPage.getByText(
        "Der vollständige juristische Name des Vereins oder Trägers",
      ),
    ).toBeVisible();

    await klaraPage
      .getByRole("button", { name: /Datenschutz & Fristen/ })
      .click();
    await expect(
      klaraPage.getByText(
        "Dieser verständliche Text wird im öffentlichen Bestellformular angezeigt",
      ),
    ).toBeVisible();

    await klaraPage.getByRole("button", { name: /Prüfen & freigeben/ }).click();
    await expect(
      klaraPage.getByText("E-Rechnungs-Grenze des Piloten"),
    ).toBeVisible();
    await klaraPage.getByLabel("E-Rechnung").selectOption("not_required");
    await klaraPage
      .getByLabel("Nachweis-ID", { exact: false })
      .fill("ERECHNUNG-PILOT-044");
    await klaraPage.getByRole("button", { name: "Entwurf speichern" }).click();
    await expect(
      klaraPage.getByText(
        "Eine andere System-Administration muss diesen Entwurf freigeben.",
      ),
    ).toBeVisible();
    await klaraPage.screenshot({
      path: `${artifactDirectory}/legal-draft-desktop.png`,
      fullPage: true,
    });

    await simonePage.goto(`${baseUrl}/admin/legal`);
    await simonePage
      .getByRole("button", { name: /Prüfen & freigeben/ })
      .click();
    await simonePage
      .getByLabel("Nachweis-ID der Freigabe")
      .fill("UI-FREIGABE-PILOT-044");
    await simonePage.getByRole("button", { name: "Entwurf freigeben" }).click();
    await expect(
      simonePage.getByText("Freigegeben von Simone System"),
    ).toBeVisible();
    await simonePage
      .getByRole("button", { name: "Version verbindlich aktivieren" })
      .click();
    await expect(simonePage.getByText("Version 2")).toBeVisible();
    await expect(simonePage.getByText("aktiv", { exact: true })).toBeVisible();

    await simonePage.setViewportSize({ width: 390, height: 844 });
    await expect(
      simonePage.getByRole("heading", { name: "Organisation & Recht" }),
    ).toBeVisible();
    await simonePage.screenshot({
      path: `${artifactDirectory}/legal-active-mobile.png`,
      fullPage: true,
    });

    await expectNoSeriousAccessibilityViolations(simonePage);
    expect(pageErrors).toEqual([]);
  } finally {
    await klaraContext.close();
    await simoneContext.close();
  }
});
