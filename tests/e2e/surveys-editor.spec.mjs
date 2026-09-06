import { test, expect } from "@playwright/test";
const baseURL = process.env.LEONAID_E2E_BASE_URL;
const token = process.env.SURVEY_ADMIN_SESSION;
if (!baseURL || !token)
  throw new Error("Authenticated survey fixture required");
test("visual page and question editing persists stable identities through the real API", async ({
  browser,
}) => {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1440, height: 1000 },
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: token,
      url: baseURL,
      secure: true,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  const page = await context.newPage();
  await page.goto(`${baseURL}/admin/surveys/new`);
  await page
    .getByLabel("Titel der Umfrage", { exact: true })
    .fill("Rückmeldung zur Aktion");
  await page
    .getByRole("button", { name: "Umfrage erstellen", exact: true })
    .click();
  const editor = page.getByRole("region", { name: "Fragebogen bearbeiten" });
  await expect(editor).toBeVisible();
  const saved = () =>
    expect(page.locator("[data-draft-state]")).toHaveAttribute(
      "data-draft-state",
      "saved",
    );
  await editor
    .getByRole("combobox", { name: "Fragetyp", exact: true })
    .selectOption("radiogroup");
  await editor
    .getByRole("button", { name: "Frage hinzufügen", exact: true })
    .click();
  await editor
    .getByLabel("Fragetitel", { exact: true })
    .fill("Wie war die Aktion?");
  await editor.getByLabel("Eintrag 1", { exact: true }).fill("Sehr gut");
  await editor
    .getByLabel("Eintrag 2", { exact: true })
    .fill("Verbesserungsbedarf");
  await saved();
  const sid = page.url().split("/").at(-1);
  const read = () =>
    page.evaluate(
      async (id) => (await fetch(`/api/v1/surveys/${id}/draft`)).json(),
      sid,
    );
  const initial = await read();
  const choice = initial.definition.pages[0].elements[1];
  const items = editor
    .getByRole("list", { name: "Fragen auf dieser Seite" })
    .locator("li");
  await items.nth(1).dragTo(items.nth(0));
  await saved();
  expect((await read()).definition.pages[0].elements[0].name).toBe(choice.name);
  await editor
    .getByRole("button", { name: "Seite duplizieren", exact: true })
    .click();
  await saved();
  const doubled = await read();
  expect(doubled.definition.pages).toHaveLength(2);
  expect(doubled.definition.pages[1].elements[0].name).not.toBe(choice.name);
  await editor.getByRole("button", { name: "Rückgängig", exact: true }).click();
  await saved();
  expect((await read()).definition.pages).toHaveLength(1);
  await editor
    .getByRole("button", { name: "Wiederholen", exact: true })
    .click();
  await saved();
  await editor
    .getByRole("button", { name: "Seite 2 nach oben", exact: true })
    .press("Enter");
  await saved();
  await page.reload();
  await expect(editor).toBeVisible();
  const restored = await read();
  expect(restored.definition.pages[1].elements[0].name).toBe(choice.name);
  expect(restored.definition.pages[1].elements[0].choices).toEqual(
    choice.choices,
  );
  await editor
    .getByRole("list", { name: "Fragen auf dieser Seite" })
    .locator("li")
    .first()
    .getByRole("button")
    .first()
    .click();
  const movingId = restored.definition.pages[0].elements[0].name;
  await editor
    .getByRole("combobox", { name: "Auf Seite verschieben", exact: true })
    .selectOption(restored.definition.pages[1].name);
  await saved();
  expect((await read()).definition.pages[1].elements[0].name).toBe(movingId);
  await editor
    .getByRole("button", { name: "Frage duplizieren", exact: true })
    .click();
  await saved();
  const beforeRemoval = await read();
  await editor
    .getByRole("button", { name: "Frage entfernen", exact: true })
    .click();
  await saved();
  expect((await read()).definition.pages[1].elements).toHaveLength(
    beforeRemoval.definition.pages[1].elements.length - 1,
  );
  await editor.getByRole("button", { name: "Rückgängig", exact: true }).click();
  await saved();
  expect((await read()).definition).toEqual(beforeRemoval.definition);
  await editor
    .getByRole("button", { name: "Frage 1 nach unten", exact: true })
    .press("Enter");
  await saved();
  expect((await read()).definition.pages[1].elements[1].name).toBe(movingId);
  await editor
    .getByRole("button", { name: "Seite entfernen", exact: true })
    .click();
  await saved();
  expect((await read()).definition.pages).toHaveLength(1);
  await editor.getByRole("button", { name: "Rückgängig", exact: true }).click();
  await saved();
  expect((await read()).definition.pages).toHaveLength(2);
  await page.screenshot({
    path: `${process.env.LEONAID_E2E_ARTIFACT_DIR}/surveys-editor.png`,
    fullPage: true,
  });
  await context.close();
});
