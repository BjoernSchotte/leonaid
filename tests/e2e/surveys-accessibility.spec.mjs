import AxeBuilder from "@axe-core/playwright";
import { test, expect } from "@playwright/test";
import { writeFile } from "node:fs/promises";

const baseURL = process.env.LEONAID_E2E_BASE_URL;
const token = process.env.SURVEY_ADMIN_SESSION;
const artifacts = process.env.LEONAID_E2E_ARTIFACT_DIR;
if (!baseURL || !token || !artifacts)
  throw new Error("Survey fixture required");

test("keyboard authoring, recovery and preview have visible focus and accessible controls", async ({
  browser,
}) => {
  test.setTimeout(180000);
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1440, height: 1000 },
    reducedMotion: "reduce",
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
  const observations = [];
  const browserErrors = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  const button = (name) => page.getByRole("button", { name, exact: true });
  const textbox = (name) => page.getByRole("textbox", { name, exact: true });
  // Real keyboard traversal: no locator.focus/click/fill/selectOption shortcuts.
  async function tabTo(target) {
    await expect(target).toBeVisible();
    for (let i = 0; i < 180; i++) {
      if (
        await target.evaluate((element) => document.activeElement === element)
      )
        return;
      await page.keyboard.press("Tab");
    }
    throw new Error(
      `Keyboard cannot reach ${(await target.getAttribute("aria-label")) || (await target.textContent())}`,
    );
  }
  async function activate(name) {
    await tabTo(button(name));
    await page.keyboard.press("Enter");
  }
  async function enter(name, value) {
    await tabTo(textbox(name));
    await page.keyboard.press("ControlOrMeta+A");
    await page.keyboard.insertText(value);
  }
  const saved = () =>
    expect(page.locator("[data-draft-state]")).toHaveAttribute(
      "data-draft-state",
      "saved",
    );
  async function scan(label) {
    const result = await new AxeBuilder({ page })
      .include(".survey-editor")
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    // axe analyzes results in a temporary page; restore the tested browser window,
    // without changing which control the keyboard journey has focused.
    await page.bringToFront();
    await expect
      .poll(() => page.evaluate(() => document.hasFocus()))
      .toBe(true);
    const manualReview = [];
    for (const finding of result.incomplete) {
      for (const node of finding.nodes) {
        if (node.target.length !== 1 || typeof node.target[0] !== "string")
          continue;
        const colors = await page
          .locator(node.target[0])
          .evaluate((element) => {
            const chain = [];
            for (
              let ancestor = element;
              ancestor;
              ancestor = ancestor.parentElement
            ) {
              const style = getComputedStyle(ancestor);
              const pseudo = getComputedStyle(ancestor, "::before");
              chain.push({
                tag: ancestor.tagName,
                class: ancestor.className,
                color: style.color,
                background: style.backgroundColor,
                image: style.backgroundImage,
                opacity: style.opacity,
                before: {
                  content: pseudo.content,
                  background: pseudo.backgroundColor,
                  image: pseudo.backgroundImage,
                  opacity: pseudo.opacity,
                },
              });
            }
            return chain;
          });
        manualReview.push({ rule: finding.id, target: node.target, colors });
      }
    }
    observations.push({
      label,
      violations: result.violations,
      incomplete: result.incomplete,
      passedRules: result.passes.length,
      manualReview,
    });
    await writeFile(
      `${artifacts}/surveys-accessibility.json`,
      JSON.stringify(observations, null, 2),
    );
    expect(result.violations, label).toEqual([]);
  }
  try {
    await page.goto(`${baseURL}/admin/surveys/new`);
    await enter("Titel der Umfrage", "Tastatur-Fragebogen");
    await activate("Umfrage erstellen");
    await expect(
      page.getByRole("region", { name: "Fragebogen bearbeiten" }),
    ).toBeVisible();
    await scan("initial editor");
    const controlColors = await textbox("Titel des Fragebogens").evaluate(
      (element) => ({
        border: getComputedStyle(element).borderTopColor,
        background: getComputedStyle(element.closest(".survey-editor"))
          .backgroundColor,
      }),
    );
    const luminance = (color) => {
      const rgb = color
        .match(/[\d.]+/g)
        .slice(0, 3)
        .map(Number)
        .map((value) => value / 255)
        .map((value) =>
          value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4,
        );
      return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
    };
    const shades = [
      luminance(controlColors.border),
      luminance(controlColors.background),
    ].sort((a, b) => a - b);
    expect((shades[1] + 0.05) / (shades[0] + 0.05)).toBeGreaterThanOrEqual(3);

    await activate("Kurzer Text Was möchten Sie uns mitteilen?");
    await enter("Fragetitel", "Ihre Rückmeldung");
    await saved();
    await scan("question properties");
    await activate("Frage duplizieren");
    await enter("Fragetitel", "Weitere Hinweise");
    await saved();
    await activate("Frage 2 nach oben");
    await expect(button("Kurzer Text Weitere Hinweise")).toBeFocused();
    await activate("Seite hinzufügen");
    await enter("Seitentitel", "Zweite Seite");
    await tabTo(page.getByRole("combobox", { name: "Fragetyp", exact: true }));
    await page.keyboard.press("Home");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await activate("Frage hinzufügen");
    await enter("Fragetitel", "Ihr Wunsch");
    await enter("Eintrag 1", "Ja");
    await enter("Eintrag 2", "Nein");
    await tabTo(
      page.getByRole("checkbox", { name: "Antwort erforderlich", exact: true }),
    );
    await page.keyboard.press("Space");
    await tabTo(page.getByRole("combobox", { name: "Fragetyp", exact: true }));
    await page.keyboard.press("Home");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await activate("Frage hinzufügen");
    await enter("Fragetitel", "Was wünschen Sie sich?");
    const rules = page
      .getByRole("complementary", { name: "Frageeigenschaften" })
      .getByRole("group", { name: "Sichtbarkeit", exact: true });
    await tabTo(
      rules.getByRole("button", { name: "Regel hinzufügen", exact: true }),
    );
    await page.keyboard.press("Enter");
    await tabTo(
      rules.getByRole("combobox", { name: "Vorherige Frage 1", exact: true }),
    );
    await page.keyboard.press("End");
    await page.keyboard.press("Enter");
    await tabTo(
      rules.getByRole("combobox", { name: "Vergleich 1", exact: true }),
    );
    await page.keyboard.press("Home");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await saved();
    await activate("Seite 2 nach oben");
    await expect(button("1. Zweite Seite")).toBeFocused();
    await expect
      .poll(
        () =>
          button("1. Zweite Seite").evaluate((element) => {
            const style = getComputedStyle(element);
            return (
              element.matches(":focus") &&
              style.outlineStyle === "solid" &&
              parseFloat(style.outlineWidth) >= 3
            );
          }),
        { message: "Moved page has an immediately visible focus ring" },
      )
      .toBe(true);
    await enter("Beschreibung", "<unsafe>");
    await saved();
    await activate("Vorschau");
    const error = page.getByRole("alert");
    await expect(error).toContainText("description");
    await expect(error).toBeFocused();
    await scan("validation error");
    await enter("Beschreibung", "Ihre Meinung hilft uns.");
    await saved();
    await activate("Vorschau");
    await expect(
      page.getByRole("heading", {
        name: "Vorschau · Antworten werden nicht gespeichert",
        exact: true,
      }),
    ).toBeFocused();
    const preview = page.getByRole("region", { name: "Fragebogen-Vorschau" });
    await expect(
      preview.getByText("Was wünschen Sie sich?", { exact: true }),
    ).toHaveCount(0);
    await tabTo(preview.getByRole("radio").first());
    await page.keyboard.press("Space");
    await expect(
      preview.getByText("Was wünschen Sie sich?", { exact: true }),
    ).toBeVisible();
    await expect(
      preview.getByRole("heading", {
        name: "Tastatur-Fragebogen",
        exact: true,
      }),
    ).toBeVisible();
    await page.screenshot({
      path: `${artifacts}/surveys-accessibility-preview.png`,
      fullPage: true,
      animations: "disabled",
    });
    await scan("respondent preview");
    await activate("Zurück zum Editor");
    await expect(button("Vorschau")).toBeFocused();
    await activate("Veröffentlichen");
    await expect(
      page.getByText("Version 1 ist veröffentlicht.", { exact: true }),
    ).toBeVisible();
    await page.reload();
    await expect(textbox("Titel des Fragebogens")).toHaveValue(
      "Tastatur-Fragebogen",
    );
    await scan("reloaded published draft");
    const id = page.url().split("/").at(-1);
    const draft = await page.evaluate(
      async (id) => (await fetch(`/api/v1/surveys/${id}/draft`)).json(),
      id,
    );
    expect(draft.definition.pages.map((item) => item.title)).toEqual([
      "Zweite Seite",
      "Ihre Rückmeldung",
    ]);
    expect(
      draft.definition.pages[1].elements.map((item) => item.title),
    ).toEqual(["Weitere Hinweise", "Ihre Rückmeldung"]);
    await page.screenshot({
      path: `${artifacts}/surveys-accessibility-editor.png`,
      fullPage: true,
    });
    expect(browserErrors).toEqual([]);
  } finally {
    await context.close();
  }
});
