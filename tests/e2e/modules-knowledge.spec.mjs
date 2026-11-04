import { test, expect } from "./csp-guard.mjs";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
const baseURL = process.env.LEONAID_E2E_BASE_URL;
const fixture = JSON.parse(
  readFileSync(process.env.LEONAID_MODULE_FIXTURE, "utf8"),
);
for (const [surface, width] of [
  ["admin", 1440],
  ["app", 390],
]) {
  test(`${surface}: edit knowledge and retain conflicting draft`, async ({
    browser,
  }, testInfo) => {
    const context = await browser.newContext({
      viewport: { width, height: 844 },
      ignoreHTTPSErrors: true,
    });
    await context.addCookies([
      {
        name: "__Host-leonaid_session",
        value: fixture.sessions[0],
        url: baseURL,
        secure: true,
        httpOnly: true,
        sameSite: "Lax",
      },
    ]);
    const page = await context.newPage();
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    const title = `Wissen Browsernachweis ${randomUUID()}`;
    await page.goto(`${baseURL}/${surface}/knowledge`);
    await page
      .getByRole("button", { name: "Seite anlegen", exact: true })
      .first()
      .click();
    const createDialog = page.getByRole("dialog", { name: "Neue Seite" });
    await createDialog.getByLabel("Seitentitel").fill(title);
    const createPageButton = createDialog.getByRole("button", {
      name: "Seite anlegen",
      exact: true,
    });
    const createPageBox = await createPageButton.boundingBox();
    expect(createPageBox.height).toBeGreaterThanOrEqual(width <= 760 ? 43 : 31);
    expect(createPageBox.height).toBeLessThanOrEqual(width <= 760 ? 48 : 40);
    await expect(createPageButton).toHaveCSS("font-weight", "600");
    // A new page opens for writing.
    await createPageButton.click();
    await expect(
      page.getByRole("heading", { level: 1, name: title, exact: true }),
    ).toBeVisible();
    const editor = page.getByRole("textbox", {
      name: "Seiteninhalt",
      exact: true,
    });
    await editor.fill("Erster gemeinsamer Inhalt.");
    await editor.press("ControlOrMeta+a");
    const mainToolbar = page.getByRole("toolbar", {
      name: "Textformatierung",
      exact: true,
    });
    const mainRoot = page
      .locator(".knowledge-formatting")
      .filter({ has: mainToolbar });
    const mainSelect = async (name, value) => {
      const select = mainRoot.getByRole("combobox", { name, exact: true });
      if (!(await select.isVisible()))
        await mainToolbar
          .getByRole("button", { name: "Weitere Formate", exact: true })
          .click();
      await select.selectOption(value);
    };
    const mainButton = async (name) => {
      const button = mainRoot.getByRole("button", { name, exact: true });
      if (!(await button.isVisible()))
        await mainToolbar
          .getByRole("button", { name: "Weitere Formate", exact: true })
          .click();
      await button.click();
    };
    const bubble = page.getByRole("toolbar", {
      name: "Auswahl formatieren",
      exact: true,
    });
    await expect(bubble).toBeVisible();
    await bubble
      .getByRole("button", { name: "Unterstreichen", exact: true })
      .click();
    await mainSelect("Schriftart", "serif");
    await mainSelect("Schriftgröße", "18px");
    await mainButton("Zentriert");
    if (
      await mainToolbar
        .getByRole("button", { name: "Weitere Formate", exact: true })
        .isVisible()
    ) {
      await mainToolbar
        .getByRole("button", { name: "Weitere Formate", exact: true })
        .click();
    }
    await expect(editor.locator("u")).toHaveText("Erster gemeinsamer Inhalt.");
    await expect(editor.locator("p")).toHaveCSS("text-align", "center");
    await expect(editor.locator("span").first()).toHaveCSS("font-size", "18px");
    await editor.focus();
    await editor.press("ControlOrMeta+a");
    await expect(bubble).toBeVisible();
    await bubble
      .getByRole("button", { name: "Weitere Formate", exact: true })
      .click();
    await page
      .getByRole("group", { name: "Weitere Textformate", exact: true })
      .getByLabel("Schriftgröße", { exact: true })
      .selectOption("20px");
    await expect(editor.locator("span").first()).toHaveCSS("font-size", "20px");
    await bubble
      .getByRole("button", { name: "Link bearbeiten", exact: true })
      .click();
    const bubbleRoot = page.locator(".knowledge-selection-menu");
    await bubbleRoot
      .getByLabel("Link-Adresse", { exact: true })
      .fill("https://example.org/planung");
    await bubbleRoot
      .getByRole("button", { name: "Link übernehmen", exact: true })
      .click();
    await expect(editor.getByRole("link")).toHaveAttribute(
      "href",
      "https://example.org/planung",
    );
    await editor.scrollIntoViewIfNeeded();
    await editor.press("ControlOrMeta+a");
    await expect(bubble).toBeVisible();
    await expect
      .poll(async () => {
        const menu = await bubbleRoot.boundingBox();
        const text = await editor.locator("p").first().boundingBox();
        return Math.min(
          Math.abs(menu.y + menu.height - text.y),
          Math.abs(menu.y - text.y - text.height),
        );
      })
      .toBeLessThan(24);
    // No tool is cut off: whole groups wrap inside the 856 px format bar.
    const mainOverflow = await mainToolbar.evaluate((bar) => {
      const frame = bar.getBoundingClientRect();
      return [...bar.querySelectorAll("button, select")]
        .filter((tool) => tool.getClientRects().length)
        .filter((tool) => {
          const box = tool.getBoundingClientRect();
          return box.right > frame.right + 1 || box.left < frame.left - 1;
        }).length;
    });
    expect(mainOverflow).toBe(0);
    const menuBounds = await bubbleRoot.boundingBox();
    const iconBounds = await bubble.getByRole("button").evaluateAll((buttons) =>
      buttons.map((button) => ({
        y: button.getBoundingClientRect().y,
        height: button.getBoundingClientRect().height,
      })),
    );
    expect(new Set(iconBounds.map(({ y }) => Math.round(y))).size).toBe(1);
    expect(await bubble.locator("svg").count()).toBe(6);
    expect(menuBounds.x).toBeGreaterThanOrEqual(0);
    expect(menuBounds.x + menuBounds.width).toBeLessThanOrEqual(width);
    await page.screenshot({
      path: testInfo.outputPath(`${surface}-knowledge-selection.png`),
      fullPage: false,
    });
    await bubble.getByRole("button", { name: "Fett", exact: true }).focus();
    await page.keyboard.press("Escape");
    await expect(bubble).not.toBeVisible();
    await page.screenshot({
      path: testInfo.outputPath(`${surface}-knowledge-formatting.png`),
      fullPage: true,
    });

    await page.getByRole("button", { name: /^Speichern/ }).click();
    await expect(page.getByText("Gespeichert.", { exact: true })).toBeVisible();
    const second = await context.newPage();
    await second.goto(
      page
        .url()
        .replace(`/${surface}/`, surface === "admin" ? "/app/" : "/admin/"),
    );
    await expect(
      second.getByRole("textbox", { name: "Seiteninhalt", exact: true }),
    ).toHaveText("Erster gemeinsamer Inhalt.");
    // Saving ends writing; both sessions read until "Bearbeiten".
    await expect(editor).toHaveAttribute("contenteditable", "false");
    const reopened = second.getByRole("textbox", {
      name: "Seiteninhalt",
      exact: true,
    });
    await expect(reopened.locator("u")).toHaveText(
      "Erster gemeinsamer Inhalt.",
    );
    await expect(reopened.locator("p")).toHaveCSS("text-align", "center");
    await expect(reopened.locator("span").first()).toHaveCSS(
      "font-size",
      "20px",
    );
    await expect(reopened.getByRole("link")).toHaveAttribute(
      "href",
      "https://example.org/planung",
    );
    await page.getByRole("button", { name: /^Bearbeiten/ }).click();
    await editor.fill("Lokaler Entwurf bleibt erhalten.");
    await second.getByRole("button", { name: /^Bearbeiten/ }).click();
    await second
      .getByRole("textbox", { name: "Seiteninhalt", exact: true })
      .fill("Andere Sitzung hat gespeichert.");
    await second.getByRole("button", { name: /^Speichern/ }).click();
    await expect(
      second.getByText("Gespeichert.", { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: /^Speichern/ }).click();
    const conflict = page.getByRole("alert").filter({
      hasText: /Die Seite wurde inzwischen geändert/,
    });
    await expect(conflict).toBeVisible();
    await expect(editor).toHaveText("Lokaler Entwurf bleibt erhalten.");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath(`${surface}-knowledge-conflict.png`),
      fullPage: false,
    });
    // The person chooses: here they take the other session's revision.
    await conflict
      .getByRole("button", { name: "Andere übernehmen", exact: true })
      .click();
    // Taking the other revision drops the draft: asked first.
    await page
      .getByRole("alertdialog", { name: "Entwurf verwerfen?" })
      .getByRole("button", { name: "Verwerfen" })
      .click();
    await expect(editor).toHaveText("Andere Sitzung hat gespeichert.");
    await expect(conflict).toHaveCount(0);
    expect(pageErrors).toEqual([]);
    await context.close();
  });
}
