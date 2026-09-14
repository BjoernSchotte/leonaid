import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";

const baseURL = process.env.LEONAID_E2E_BASE_URL;
const fixture = JSON.parse(
  readFileSync(process.env.LEONAID_MODULE_FIXTURE, "utf8"),
);
async function session(browser, width, user = 0) {
  const context = await browser.newContext({
    viewport: { width, height: 844 },
    hasTouch: width === 390,
    ignoreHTTPSErrors: true,
    permissions: ["clipboard-read", "clipboard-write"],
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: fixture.sessions[user],
      url: baseURL,
      secure: true,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  return context;
}
async function createPage(page, surface) {
  const title = `Redaktionsprobe ${randomUUID()}`;
  await page.goto(`${baseURL}/${surface}/knowledge`);
  await page.getByText("Neue Seite", { exact: true }).click();
  await page.getByLabel("Seitentitel", { exact: true }).fill(title);
  await page
    .getByRole("button", { name: "Seite anlegen", exact: true })
    .click();
  await page.getByRole("link", { name: title, exact: true }).click();
  return page.getByRole("textbox", { name: "Seiteninhalt", exact: true });
}

for (const [surface, width] of [
  ["admin", 1440],
  ["app", 390],
]) {
  test(`${surface}: clipboard, partial selection, lists and history`, async ({
    browser,
  }, testInfo) => {
    const context = await session(browser, width);
    const page = await context.newPage();
    const editor = await createPage(page, surface);
    const toolbar = page.getByRole("toolbar", {
      name: "Textformatierung",
      exact: true,
    });
    const mainRoot = page
      .locator(".knowledge-formatting")
      .filter({ has: toolbar });
    const action = (name) =>
      mainRoot.getByRole("button", { name, exact: true });
    const clickAction = async (name) => {
      if (!(await action(name).isVisible()))
        await toolbar
          .getByRole("button", { name: "Weitere Formate", exact: true })
          .click();
      await action(name).click();
      await expect(editor).toBeFocused();
    };
    await editor.click();
    await editor.pressSequentially("Gemeinsam planen");
    await expect(editor).toHaveText("Gemeinsam planen");
    await editor.press("ControlOrMeta+a");
    await expect
      .poll(() => page.evaluate(() => window.getSelection()?.toString()))
      .toBe("Gemeinsam planen");
    await page.keyboard.press("ArrowLeft");
    for (let character = 0; character < "Gemeinsam".length; character++)
      await page.keyboard.press("Shift+ArrowRight");
    await expect
      .poll(() => page.evaluate(() => window.getSelection()?.toString()))
      .toBe("Gemeinsam");
    await clickAction("Fett");
    await action("Fett").focus();
    await page.keyboard.press("ArrowRight");
    await expect(action("Kursiv")).toBeFocused();
    await expect(editor.locator("strong")).toHaveText(/Gemeinsam/);
    await expect(editor.locator("strong")).not.toContainText("planen");
    await editor.press("ControlOrMeta+a");
    await expect(action("Fett")).toHaveAttribute("aria-pressed", "false");
    const heading = mainRoot.getByRole("combobox", {
      name: "Absatzformat",
      exact: true,
    });
    if (!(await heading.isVisible()))
      await toolbar
        .getByRole("button", { name: "Weitere Formate", exact: true })
        .click();
    await heading.selectOption("2");
    await expect(editor.locator("h2")).toHaveText("Gemeinsam planen");
    await clickAction("Rückgängig");
    await expect(editor.locator("h2")).toHaveCount(0);
    await clickAction("Wiederholen");
    await expect(editor.locator("h2")).toHaveText("Gemeinsam planen");

    await page.evaluate(async () =>
      navigator.clipboard.write([
        new ClipboardItem({
          "text/html": new Blob(
            [
              '<p><span style="font-family: Arial; font-size: 17pt">Aus Word eingefügt</span> <strong>bleibt fett</strong> <a href="https://example.org/redaktion" class="foreign-link" target="_parent" rel="external">Quelle</a></p><p><span style="font-family: serif; font-size: 20px">Erlaubte Schrift</span></p>',
            ],
            { type: "text/html" },
          ),
        }),
      ]),
    );
    await editor.press("ControlOrMeta+a");
    await editor.press("ControlOrMeta+v");
    await expect(editor).toContainText("Aus Word eingefügt");
    await expect(editor.locator("strong")).toHaveText("bleibt fett");
    await expect(
      editor.getByRole("link", { name: "Quelle", exact: true }),
    ).toHaveAttribute("href", "https://example.org/redaktion");
    await expect(editor.locator('span[style*="Arial"]')).toHaveCount(0);
    await expect(
      editor.getByText("Erlaubte Schrift", { exact: true }),
    ).toHaveCSS("font-size", "20px");
    await editor.press("ControlOrMeta+a");
    await editor.press("ControlOrMeta+c");
    expect(await page.evaluate(() => navigator.clipboard.readText())).toContain(
      "Aus Word eingefügt",
    );
    await page.getByRole("button", { name: "Speichern", exact: true }).click();
    await expect(page.getByText("Gespeichert.", { exact: true })).toBeVisible();
    await page.reload();
    await expect(editor).toContainText("Aus Word eingefügt");
    await expect(editor.locator("strong")).toHaveText("bleibt fett");

    await editor.press("ControlOrMeta+End");
    await editor.press("Enter");
    await clickAction("Aufzählung");
    await page.keyboard.type("Erster Punkt");
    await page.keyboard.press("Enter");
    await page.keyboard.type("Zweiter Punkt");
    await clickAction("Einrücken");
    await expect(editor.locator("ul ul li")).toContainText("Zweiter Punkt");
    await clickAction("Ausrücken");
    await expect(editor.locator("ul ul")).toHaveCount(0);
    await clickAction("Nummerierte Liste");
    await expect(editor.locator("ol > li")).toHaveCount(2);
    const more = toolbar.getByRole("button", {
      name: "Weitere Formate",
      exact: true,
    });
    if (
      (await more.isVisible()) &&
      (await more.getAttribute("aria-expanded")) === "true"
    )
      await more.click();
    const toolbarPositions = await toolbar
      .getByRole("button")
      .evaluateAll((buttons) =>
        buttons
          .filter((button) => button.getClientRects().length)
          .map((button) => Math.round(button.getBoundingClientRect().y)),
      );
    expect(new Set(toolbarPositions).size).toBe(1);
    // Target the rendered word, not the whitespace in the full-width list row.
    const firstItem = editor.locator("ol > li").first();
    await firstItem.scrollIntoViewIfNeeded();
    const word = await firstItem.evaluate((item) => {
      const text = document
        .createTreeWalker(item, NodeFilter.SHOW_TEXT)
        .nextNode();
      const range = document.createRange();
      range.setStart(text, 0);
      range.setEnd(text, "Erster".length);
      const rect = range.getBoundingClientRect();
      return { x: rect.x + 4, y: rect.y + rect.height / 2 };
    });
    await page.mouse.dblclick(word.x, word.y);
    await expect
      .poll(() => page.evaluate(() => window.getSelection()?.toString()))
      .toBe("Erster");
    const bubble = page.getByRole("toolbar", {
      name: "Auswahl formatieren",
      exact: true,
    });
    await expect(bubble).toBeVisible();
    await bubble.getByRole("button", { name: "Kursiv", exact: true }).click();
    await expect(editor.locator("ol em")).toHaveCount(1);
    const target = await bubble
      .getByRole("button", { name: "Fett", exact: true })
      .boundingBox();
    expect(target.height).toBeGreaterThanOrEqual(width === 390 ? 44 : 36);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath(`${surface}-editor-acceptance.png`),
    });
    await page.getByRole("button", { name: "Speichern", exact: true }).click();
    await expect(page.getByText("Gespeichert.", { exact: true })).toBeVisible();
    await page.reload();
    await expect(editor.locator("ol > li")).toHaveCount(2);
    await expect(editor.locator("ol em")).toHaveCount(1);
    await context.close();
  });
}

test("insert task/material and preserve viewer permissions", async ({
  browser,
}, testInfo) => {
  const owner = await session(browser, 1440);
  const reader = await session(browser, 390, 1);
  const page = await owner.newPage();
  const suffix = randomUUID();
  const listTitle = `Redaktionsliste ${suffix}`;
  await page.goto(`${baseURL}/admin/tasks`);
  await page.getByText("Neue Liste", { exact: true }).click();
  await page.getByLabel("Name der Liste", { exact: true }).fill(listTitle);
  await page
    .getByRole("button", { name: "Liste anlegen", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Neue Aufgabe", exact: true }),
  ).toBeVisible();
  await page.goto(`${baseURL}/admin/materials`);
  await page.getByText("Neues Material", { exact: true }).click();
  const materialTitle = `Redaktionsmaterial ${suffix}`;
  await page.getByLabel("Materialtitel", { exact: true }).fill(materialTitle);
  await page.getByLabel("Datei", { exact: true }).setInputFiles({
    name: "redaktion.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Redaktionsmaterial\n"),
  });
  await page.getByRole("button", { name: "Hochladen", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: materialTitle, exact: true }),
  ).toBeVisible();
  const editor = await createPage(page, "admin");
  await editor.fill("Planung mit Aufgabe und Material");
  await page.getByRole("button", { name: "Speichern", exact: true }).click();
  await expect(page.getByText("Gespeichert.", { exact: true })).toBeVisible();
  await page.getByText("Einfügen", { exact: true }).click();
  await page
    .getByRole("button", {
      name: "Material aus Ablage verknüpfen",
      exact: true,
    })
    .click();
  await page
    .getByLabel("Materialien zum Verknüpfen suchen", { exact: true })
    .fill(materialTitle);
  await page.getByRole("button", { name: materialTitle, exact: true }).click();
  await page
    .getByRole("button", { name: "Dateiversion einfügen", exact: true })
    .click();
  await expect(editor).toContainText("redaktion.txt · Dateiversion 1");
  await page.getByRole("button", { name: "Speichern", exact: true }).click();
  await expect(page.getByText("Gespeichert.", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Aufgabe aus dieser Seite", exact: true })
    .click();
  await page
    .getByLabel("Aufgabenlisten suchen", { exact: true })
    .fill(listTitle);
  await page.getByRole("button", { name: listTitle, exact: true }).click();
  const taskForm = page.getByRole("form", {
    name: "Neue Aufgabe",
    exact: true,
  });
  await taskForm.getByLabel("Titel", { exact: true }).fill("Redaktion prüfen");
  await taskForm
    .getByRole("button", { name: "Speichern", exact: true })
    .click();
  await expect(taskForm).toHaveCount(0);
  await expect(
    editor.getByRole("link", { name: "Redaktion prüfen · Offen", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(editor).toContainText("redaktion.txt · Dateiversion 1");
  await expect(editor).toContainText("Redaktion prüfen · Offen");
  await page.screenshot({
    path: testInfo.outputPath("admin-editor-references.png"),
    fullPage: true,
  });

  const identity = await reader.request.get(`${baseURL}/api/v1/identity/me`);
  expect(identity.ok()).toBe(true);
  const { email } = await identity.json();
  await page.getByText("Freigaben verwalten", { exact: true }).click();
  await page
    .getByRole("button", { name: "Seitenfreigaben", exact: true })
    .click();
  await page.getByLabel("E-Mail-Adresse", { exact: true }).fill(email);
  await page
    .getByRole("button", { name: "Zugriff speichern", exact: true })
    .click();
  await expect(
    page.getByText("Zugriff gespeichert.", { exact: true }),
  ).toBeVisible();
  const view = await reader.newPage();
  await view.goto(page.url().replace("/admin/", "/app/"));
  const readOnly = view.getByRole("textbox", {
    name: "Seiteninhalt",
    exact: true,
  });
  await expect(readOnly).toHaveAttribute("contenteditable", "false");
  await expect(readOnly).toContainText("Planung mit Aufgabe und Material");
  await expect(view.getByRole("toolbar")).toHaveCount(0);
  await expect(
    view.getByRole("button", { name: "Speichern", exact: true }),
  ).toHaveCount(0);
  await expect(readOnly).toContainText("Material nicht verfügbar");
  await expect(readOnly).toContainText("Aufgabe nicht verfügbar");
  await view.screenshot({
    path: testInfo.outputPath("app-editor-readonly.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Seitenzugriff entfernen", exact: true })
    .click();
  await expect(
    page.getByText("Keine zusätzlichen Mitglieder für diese Suche.", {
      exact: true,
    }),
  ).toBeVisible();
  await view.reload();
  await expect(readOnly).toHaveCount(0);
  await owner.close();
  await reader.close();
});
