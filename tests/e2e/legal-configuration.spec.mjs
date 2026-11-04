import { analyzeAccessibility } from "./axe.mjs";
import { expect, test } from "./csp-guard.mjs";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const simoneSession = process.env.SIMONE_SESSION;
const klaraSession = process.env.KLARA_SESSION;

if (!baseUrl || !artifactDirectory || !simoneSession || !klaraSession) {
  throw new Error("PILOT-044 browser environment is incomplete");
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
  const accessibility = await analyzeAccessibility(page);
  expect(
    accessibility.violations.filter(
      (violation) =>
        violation.impact === "critical" || violation.impact === "serious",
    ),
  ).toEqual([]);
}

test("two system admins activate a legal basis", async ({ browser }) => {
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
      klaraPage.getByRole("heading", { level: 1, name: "Rechtliches" }),
    ).toBeVisible();
    // Seeded: draft version 1 is approved, but the open e-invoice decision
    // blocks its activation (tools/legal_configuration/contract.py).
    await expect(
      klaraPage.getByText("Entwurf Version 1 freigegeben, Aktivierung offen"),
    ).toBeVisible();
    await expect(
      klaraPage.getByText("Noch keine aktive Version"),
    ).toBeVisible();
    await expect(klaraPage.getByTestId("legal-blockers")).toContainText(
      "Die E-Rechnungs-Pflicht ist noch nicht entschieden.",
    );
    await expect(
      klaraPage.getByRole("button", { name: /aktivieren/ }),
    ).toHaveCount(0);
    await expect(
      klaraPage.getByRole("heading", { level: 2, name: "Träger & Anschrift" }),
    ).toBeVisible();

    const parts = klaraPage.getByRole("navigation", {
      name: "Bereiche der rechtlichen Angaben",
    });
    await parts.getByRole("link", { name: /Datenschutz/ }).click();
    await expect(klaraPage).toHaveURL(/\/admin\/legal\/privacy$/);
    await expect(
      klaraPage.getByText(
        "Auskunft, Sperre und Anonymisierung einzelner Personen",
      ),
    ).toBeVisible();

    await parts.getByRole("link", { name: /E-Rechnung/ }).click();
    await expect(klaraPage).toHaveURL(/\/admin\/legal\/e-invoice$/);
    await klaraPage
      .getByTestId("legal-next-step")
      .getByRole("button", { name: "Entwurf bearbeiten" })
      .click();
    const editor = klaraPage.getByTestId("legal-editor");
    await editor.getByLabel(/^E-Rechnung/).selectOption("not_required");
    await editor
      .getByLabel(/Nachweis-ID der Entscheidung/)
      .fill("ERECHNUNG-PILOT-044");
    await editor.getByRole("button", { name: "Als Entwurf speichern" }).click();

    // The author never gets the approval; the server refuses it as well.
    const klaraDraft = klaraPage.getByTestId("legal-draft");
    await expect(klaraDraft).toContainText("Entwurf Version 2");
    await expect(klaraDraft).toContainText("Wartet auf zweite Freigabe");
    await expect(klaraPage.getByTestId("legal-author-lock")).toContainText(
      "Sie haben diesen Entwurf erstellt. Freigeben muss eine andere Person",
    );
    await expect(
      klaraPage.getByRole("button", { name: "Entwurf freigeben" }),
    ).toHaveCount(0);
    await expect(
      klaraPage.getByRole("button", { name: /aktivieren/ }),
    ).toHaveCount(0);
    await klaraPage.screenshot({
      path: `${artifactDirectory}/legal-draft-desktop.png`,
      fullPage: true,
    });

    await simonePage.goto(`${baseUrl}/admin/legal/e-invoice`);
    const draft = simonePage.getByTestId("legal-draft");
    await expect(draft).toContainText("Nicht erforderlich");
    await expect(
      simonePage.getByRole("button", { name: /aktivieren/ }),
    ).toHaveCount(0);
    await simonePage
      .getByLabel("Nachweis-ID der Freigabe")
      .fill("UI-FREIGABE-PILOT-044");
    await simonePage.getByRole("button", { name: "Entwurf freigeben" }).click();
    await expect(simonePage.getByTestId("legal-approvals")).toContainText(
      "Freigegeben von Simone System",
    );
    await simonePage
      .getByRole("button", { name: "Version 2 aktivieren" })
      .click();
    await simonePage
      .getByRole("alertdialog", { name: "Version 2 aktivieren?" })
      .getByRole("button", { name: "Jetzt aktivieren" })
      .click();
    await expect(simonePage.getByText("Version 2 aktiv")).toBeVisible();
    await expect(simonePage.getByText("Kein offener Entwurf")).toBeVisible();

    await simonePage.setViewportSize({ width: 390, height: 844 });
    await expect(
      simonePage.getByRole("heading", { level: 1, name: "Rechtliches" }),
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
