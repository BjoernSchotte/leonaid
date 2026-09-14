import { test, expect } from "@playwright/test";
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
    const title = `Wissen Browsernachweis ${randomUUID()}`;
    await page.goto(`${baseURL}/${surface}/knowledge`);
    await page.getByText("Neue Seite", { exact: true }).click();
    await page.getByLabel("Seitentitel", { exact: true }).fill(title);
    await page
      .getByRole("button", { name: "Seite anlegen", exact: true })
      .click();
    await page.getByRole("link", { name: title, exact: true }).click();
    const editor = page.getByRole("textbox", {
      name: "Seiteninhalt",
      exact: true,
    });
    await editor.fill("Erster gemeinsamer Inhalt.");
    await editor.press("ControlOrMeta+a");
    await page
      .getByRole("button", { name: "Unterstreichen", exact: true })
      .click();
    await page.getByLabel("Schriftart", { exact: true }).selectOption("serif");
    await page.getByLabel("Schriftgröße", { exact: true }).selectOption("18px");
    await page.getByRole("button", { name: "Zentriert", exact: true }).click();
    await expect(editor.locator("u")).toHaveText("Erster gemeinsamer Inhalt.");
    await expect(editor.locator("p")).toHaveCSS("text-align", "center");
    await expect(editor.locator("span").first()).toHaveCSS("font-size", "18px");
    await page.screenshot({
      path: testInfo.outputPath(`${surface}-knowledge-formatting.png`),
      fullPage: true,
    });

    await page.getByRole("button", { name: "Speichern", exact: true }).click();
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
      "18px",
    );
    await editor.fill("Lokaler Entwurf bleibt erhalten.");
    await second
      .getByRole("textbox", { name: "Seiteninhalt", exact: true })
      .fill("Andere Sitzung hat gespeichert.");
    await second
      .getByRole("button", { name: "Speichern", exact: true })
      .click();
    await expect(
      second.getByText("Gespeichert.", { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Speichern", exact: true }).click();
    await expect(
      page.getByText(/Die Seite wurde inzwischen geändert/),
    ).toBeVisible();
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
    page.once("dialog", (dialog) => dialog.dismiss());
    await page
      .getByRole("button", { name: "Aktuelle Version laden", exact: true })
      .click();
    await expect(editor).toHaveText("Lokaler Entwurf bleibt erhalten.");
    page.once("dialog", (dialog) => dialog.accept());
    await page
      .getByRole("button", { name: "Aktuelle Version laden", exact: true })
      .click();
    await expect(editor).toHaveText("Andere Sitzung hat gespeichert.");
    await context.close();
  });
}
