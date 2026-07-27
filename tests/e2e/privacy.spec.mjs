import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const simoneSession = process.env.SIMONE_SESSION;
const subjectEmail = "mara.muster@musterwerk.leonaid.invalid";

if (!baseUrl || !artifactDirectory || !simoneSession) {
  throw new Error("POC-111 Browserumgebung ist unvollständig");
}

test.setTimeout(120_000);

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

async function streamText(stream) {
  let value = "";
  for await (const chunk of stream) value += chunk.toString();
  return value;
}

test("System-Admin führt Auskunft, Sperre und Anonymisierung kontrolliert aus", async ({
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
    await page.goto(`${baseUrl}/admin/privacy`);
    await expect(
      page.getByRole("heading", { name: "Datenschutz-Vorgänge" }),
    ).toBeVisible();
    await page.getByTestId("privacy-email").fill(subjectEmail);
    await page.getByRole("button", { name: "Daten prüfen" }).click();
    await expect(page.getByTestId("privacy-summary")).toContainText(
      subjectEmail,
    );
    await expect(page.getByText("KT26-0002", { exact: true })).toBeVisible();
    await expect(
      page.getByRole("heading", {
        name: "Offene Entscheidungen – keine Rechtsannahmen",
      }),
    ).toBeVisible();

    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "JSON-Auskunft laden" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(
      /^leonaid-datenauskunft-\d{4}-\d{2}-\d{2}\.json$/,
    );
    const exported = JSON.parse(
      await streamText(await download.createReadStream()),
    );
    expect(exported.subjectEmail).toBe(subjectEmail);
    expect(
      exported.references.some(
        (item) => item.id === "90000000-0000-4000-8000-000000000002",
      ),
    ).toBe(true);
    expect(JSON.stringify(exported)).not.toContain(
      "80000000-0000-4000-8000-000000000006",
    );

    await page.getByRole("button", { name: "Kontakt sperren" }).click();
    await expect(
      page.getByRole("heading", { name: "Folgendkontakt sperren?" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Kontakt jetzt sperren" }).click();
    await expect(page.getByText("Folgendkontakt gesperrt")).toBeVisible();
    await page.screenshot({
      path: `${artifactDirectory}/privacy-before-erasure.png`,
      fullPage: true,
    });

    await page.getByTestId("privacy-erasure-confirmation").fill(subjectEmail);
    await page.getByRole("button", { name: "Anonymisierung prüfen" }).click();
    await expect(
      page.getByRole("heading", {
        name: "Anonymisierung verbindlich ausführen?",
      }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Operative Daten anonymisieren" })
      .click();
    await expect(page.getByText("Anonymisierung abgeschlossen")).toBeVisible();
    await expect(
      page.getByText(/Rechnung\(en\).*unverändert erhalten/),
    ).toBeVisible();

    await page.setViewportSize({ width: 390, height: 844 });
    await expect(
      page.getByRole("heading", { name: "Datenschutz-Vorgänge" }),
    ).toBeVisible();
    await page.screenshot({
      path: `${artifactDirectory}/privacy-after-erasure-mobile.png`,
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
