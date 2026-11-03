import { test, expect } from "./csp-guard.mjs";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";

const baseURL = process.env.LEONAID_E2E_BASE_URL;
const fixture = JSON.parse(
  readFileSync(process.env.LEONAID_MODULE_FIXTURE, "utf8"),
);

async function sessionContext(browser, session, width) {
  const context = await browser.newContext({
    viewport: { width, height: 844 },
    ignoreHTTPSErrors: true,
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: session,
      url: baseURL,
      secure: true,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  return context;
}

async function expectNoHorizontalScroll(page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
}

for (const [surface, shell, width] of [
  ["web", "/admin", 1440],
  ["pwa", "/app", 390],
]) {
  test(`${surface}: handle a case with note, status and a file version`, async ({
    browser,
  }, testInfo) => {
    const context = await sessionContext(browser, fixture.sessions[0], width);
    const page = await context.newPage();
    const caseURL = `${baseURL}${shell}/inbox/${fixture.cases[surface]}`;

    // A material version to link, uploaded through the real materials module.
    const title = `Inbox Material ${surface} ${randomUUID()}`;
    const original = Buffer.from("Ablaufplan für den Mittagstisch.\n");
    await page.goto(`${baseURL}${shell}/materials`);
    await page.getByText("Neues Material", { exact: true }).click();
    await page.getByLabel("Materialtitel", { exact: true }).fill(title);
    await page.getByLabel("Datei", { exact: true }).setInputFiles({
      name: "ablauf.txt",
      mimeType: "text/plain",
      buffer: original,
    });
    await page.getByRole("button", { name: "Hochladen", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: title, exact: true }),
    ).toBeVisible();

    await page.goto(`${baseURL}${shell}/inbox`);
    await page
      .getByRole("link", { name: new RegExp(`Mittagstisch \\(${surface}\\)`) })
      .click();
    await expect(page).toHaveURL(caseURL);
    await expect(
      page.getByText("Guten Tag,", { exact: false }).first(),
    ).toBeVisible();

    const note = `Termin am Donnerstag prüfen ${randomUUID()}`;
    await page.getByLabel("Neue Notiz", { exact: true }).fill(note);
    await page.getByRole("button", { name: "Notiz speichern", exact: true }).click();
    await expect(page.getByText(note, { exact: true })).toBeVisible();

    await page.getByLabel("Status", { exact: true }).selectOption("in_progress");
    await page
      .getByRole("button", { name: "Bearbeitung speichern", exact: true })
      .click();
    await expect(page.getByText("Bearbeitung gespeichert.")).toBeVisible();

    const linkMaterialButton = page.getByRole("button", {
      name: "Material verknüpfen",
      exact: true,
    });
    const linkBox = await linkMaterialButton.boundingBox();
    expect(linkBox.height).toBeGreaterThanOrEqual(width <= 760 ? 44 : 40);
    expect(linkBox.height).toBeLessThanOrEqual(width <= 760 ? 48 : 44);
    await linkMaterialButton.click();
    await page
      .getByLabel("Materialien zum Verknüpfen suchen", { exact: true })
      .fill(title);
    await page.getByRole("button", { name: title, exact: true }).click();
    await page
      .getByRole("button", { name: "Dateiversion einfügen", exact: true })
      .click();
    await expect(
      page.getByText("ablauf.txt · Dateiversion 1", { exact: true }),
    ).toBeVisible();
    const download = page.waitForEvent("download");
    await page
      .getByRole("button", { name: "Dateiversion herunterladen", exact: true })
      .click();
    expect(readFileSync(await (await download).path())).toEqual(original);
    await expectNoHorizontalScroll(page);
    await page.screenshot({
      path: testInfo.outputPath(`${surface}-inbox-case.png`),
      fullPage: false,
    });

    // The state survives a reload from the server.
    await page.reload();
    await expect(page.getByLabel("Status", { exact: true })).toHaveValue(
      "in_progress",
    );
    await expect(page.getByText(note, { exact: true })).toBeVisible();
    await page
      .getByRole("button", { name: "Verweis entfernen", exact: true })
      .click();
    await expect(
      page.getByText("Noch keine Materialien verknüpft.", { exact: true }),
    ).toBeVisible();
    await context.close();

    // An unrelated account neither lists nor opens the case.
    const foreign = await sessionContext(browser, fixture.sessions[1], width);
    const denied = await foreign.newPage();
    await denied.goto(caseURL);
    await expect(
      denied.getByText(
        "Dieser Eingang ist nicht mehr verfügbar oder du hast keinen Zugriff.",
      ),
    ).toBeVisible();
    await expect(denied.getByText(note, { exact: true })).toHaveCount(0);
    await foreign.close();
  });
}
