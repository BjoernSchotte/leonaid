import { test, expect } from "./csp-guard.mjs";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { uploadMaterial } from "./material-list.mjs";

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
    await uploadMaterial(page, baseURL, shell, {
      title,
      file: { name: "ablauf.txt", mimeType: "text/plain", buffer: original },
    });

    await page.goto(`${baseURL}${shell}/inbox`);
    await expect(
      page.getByRole("heading", { level: 1, name: "Eingang" }),
    ).toBeVisible();
    await page
      .getByRole("link", { name: new RegExp(`Mittagstisch \\(${surface}\\)`) })
      .click();
    await expect(page).toHaveURL(
      new RegExp(`${shell}/inbox\\?(?:.*&)?open=${fixture.cases[surface]}`),
    );
    // The desktop pane is an aside; at 390 px it is a modal sheet.
    const pane =
      width <= 720
        ? page.getByRole("dialog", { name: /Rückfrage zum Mittagstisch/ })
        : page.getByRole("complementary", {
            name: /Details: Rückfrage zum Mittagstisch/,
          });
    await expect(pane).toBeVisible();
    await expect(
      pane.getByText("Guten Tag,", { exact: false }).first(),
    ).toBeVisible();
    await expect(pane.getByText(/mit Einwilligung/)).toBeVisible();

    const note = `Termin am Donnerstag prüfen ${randomUUID()}`;
    await pane.getByLabel("Interne Notiz", { exact: true }).fill(note);
    await pane.getByRole("button", { name: "Hinzufügen", exact: true }).click();
    await expect(pane.getByText(note, { exact: true })).toBeVisible();

    await pane
      .getByRole("group", { name: "Eigenschaften" })
      .getByRole("button", { name: /^Status/ })
      .click();
    await page.getByRole("option", { name: /In Bearbeitung/ }).click();
    await expect(
      pane
        .getByRole("group", { name: "Eigenschaften" })
        .getByRole("button", { name: /^Status/ }),
    ).toContainText("In Bearbeitung");

    const linkMaterialButton = pane.getByRole("button", {
      name: "Material verknüpfen",
      exact: true,
    });
    const linkBox = await linkMaterialButton.boundingBox();
    // Compact 28 px on desktop (prototype), 44 px touch target at 390 px.
    expect(linkBox.height).toBeGreaterThanOrEqual(width <= 760 ? 44 : 28);
    expect(linkBox.height).toBeLessThanOrEqual(width <= 760 ? 48 : 32);
    await linkMaterialButton.click();
    await pane
      .getByLabel("Materialien zum Verknüpfen suchen", { exact: true })
      .fill(title);
    await pane.getByRole("button", { name: title, exact: true }).click();
    await pane
      .getByRole("button", { name: "Dateiversion einfügen", exact: true })
      .click();
    const fileChip = pane.getByRole("button", {
      name: "ablauf.txt · Dateiversion 1",
      exact: true,
    });
    await expect(fileChip).toBeVisible();
    const download = page.waitForEvent("download");
    await fileChip.click();
    expect(readFileSync(await (await download).path())).toEqual(original);
    await expectNoHorizontalScroll(page);
    await page.screenshot({
      path: testInfo.outputPath(`${surface}-inbox-case.png`),
      fullPage: false,
    });

    // The state survives a reload from the server; the old case path still
    // opens the case.
    await page.goto(caseURL);
    await expect(
      pane
        .getByRole("group", { name: "Eigenschaften" })
        .getByRole("button", { name: /^Status/ }),
    ).toContainText("In Bearbeitung");
    await expect(pane.getByText(note, { exact: true })).toBeVisible();
    await pane
      .getByRole("button", {
        name: "Verweis entfernen: ablauf.txt · Dateiversion 1",
        exact: true,
      })
      .click();
    await expect(
      pane.getByText("Nichts verknüpft.", { exact: true }),
    ).toBeVisible();

    // Closing asks for an internal note first.
    await pane
      .getByRole("button", { name: "Abschließen …", exact: true })
      .click();
    const closeDialog = page.getByRole("dialog", {
      name: "Anfrage abschließen",
    });
    await expect(closeDialog).toBeVisible();
    await closeDialog
      .getByRole("button", { name: "Abschließen", exact: true })
      .click();
    await expect(closeDialog.getByText(/mindestens 10 Zeichen/)).toBeVisible();
    await closeDialog
      .getByLabel(/Abschlussnotiz/)
      .fill("Termin telefonisch vereinbart.");
    await closeDialog
      .getByRole("button", { name: "Abschließen", exact: true })
      .click();
    await expect(closeDialog).toHaveCount(0);
    await expect(
      pane.getByText("Abschlussnotiz: Termin telefonisch vereinbart.", {
        exact: true,
      }),
    ).toBeVisible();
    await expectNoHorizontalScroll(page);
    await context.close();

    // An unrelated account neither lists nor opens the case.
    const foreign = await sessionContext(browser, fixture.sessions[1], width);
    const denied = await foreign.newPage();
    await denied.goto(caseURL);
    await expect(
      denied.getByText(
        surface === "web"
          ? "Dieser Eingang ist nicht mehr verfügbar oder Sie haben keinen Zugriff."
          : "Dieser Eingang ist nicht mehr verfügbar oder du hast keinen Zugriff.",
      ),
    ).toBeVisible();
    await expect(
      denied.getByRole("link", { name: /Mittagstisch/ }),
    ).toHaveCount(0);
    await expect(denied.getByText(note, { exact: true })).toHaveCount(0);
    await foreign.close();
  });
}
