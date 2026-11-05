import { test, expect } from "./csp-guard.mjs";
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
    .getByRole("button", { name: "Frage hinzufügen", exact: true })
    .click();
  await editor
    .getByRole("menu", { name: "Fragetyp" })
    .getByRole("menuitem", { name: "Einfachauswahl", exact: true })
    .click();
  await editor
    .getByLabel("Fragetitel", { exact: true })
    .fill("Wie war die Aktion?");
  await editor.getByLabel("Eintrag 1", { exact: true }).fill("Sehr gut");
  await editor
    .getByLabel("Eintrag 2", { exact: true })
    .fill("Verbesserungsbedarf");
  await editor.getByLabel("Hinweis", { exact: true }).fill("Bitte ehrlich");
  await saved();
  // The open card holds the fields; a mouse drag over their text selects
  // it instead of dragging the card (only the card head is draggable).
  // A wrapping label's name includes a filled textarea's text, hence /^…/.
  for (const label of [/^Fragetitel$/, /^Hinweis/, /^Eintrag 1$/]) {
    const field = editor.getByLabel(label);
    await field.scrollIntoViewIfNeeded();
    const box = await field.boundingBox();
    const y = box.y + Math.min(box.height / 2, 18);
    await page.mouse.move(box.x + 8, y);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width - 8, y, { steps: 8 });
    await page.mouse.up();
    expect(
      await field.evaluate(
        (element) => element.selectionEnd - element.selectionStart,
      ),
      `${label} text is selectable with the mouse`,
    ).toBeGreaterThan(0);
  }
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
  // Drag by the card head: the open card's fields are not a drag handle.
  await items
    .nth(1)
    .locator(".se-question-head")
    .dragTo(items.nth(0).locator(".se-question-head"));
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

test("leaving with unsaved settings asks once: in the page, not again by the browser", async ({
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
  const browserDialogs = [];
  page.on("dialog", (dialog) => {
    browserDialogs.push(dialog.type());
    void dialog.dismiss();
  });
  await page.goto(`${baseURL}/admin/surveys/new`);
  await page
    .getByLabel("Titel der Umfrage", { exact: true })
    .fill("Einmal fragen");
  await page
    .getByRole("button", { name: "Umfrage erstellen", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Fragebogen bearbeiten" }),
  ).toBeVisible();
  await expect(page.locator("[data-draft-state]")).toHaveAttribute(
    "data-draft-state",
    "saved",
  );
  const surveyUrl = page.url();
  await page.getByLabel("Abweichender Zeitraum in Sekunden").fill("120");
  // Still protected: a reload asks through the browser (dismissed: stay).
  await page.reload({ timeout: 3_000 }).catch(() => {});
  await expect.poll(() => browserDialogs).toEqual(["beforeunload"]);
  expect(page.url()).toBe(surveyUrl);
  // The in-page question, then no second dialog from the browser (I11).
  await page.getByRole("link", { name: "Alle Umfragen" }).click();
  const discard = page.getByRole("dialog", { name: "Entwurf verwerfen?" });
  await discard.getByRole("button", { name: "Verwerfen", exact: true }).click();
  await page.waitForURL(`${baseURL}/admin/surveys`);
  expect(browserDialogs).toEqual(["beforeunload"]);
  await context.close();
});
