import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
const fixture = JSON.parse(
  readFileSync(process.env.LEONAID_MODULE_FIXTURE, "utf8"),
);
const baseURL = process.env.LEONAID_E2E_BASE_URL;
for (const [surface, width] of [
  ["admin", 1440],
  ["app", 390],
]) {
  test(`${surface}: assign, defer and complete task without changing due date`, async ({
    browser,
  }, testInfo) => {
    const context = await browser.newContext({
      viewport: { width, height: 844 },
      timezoneId: "UTC",
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
    const title = `Aufgabe Browsernachweis ${randomUUID()}`;
    const due = new Date(Date.now() + 86400000 * 10).toISOString().slice(0, 16);
    const deferred = new Date(Date.now() + 86400000 * 2)
      .toISOString()
      .slice(0, 16);
    await page.goto(`${baseURL}/${surface}/tasks`);
    await page
      .getByLabel("Name der Liste", { exact: true })
      .fill(`Liste ${title}`);
    await page
      .getByRole("button", { name: "Liste anlegen", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Neue Aufgabe", exact: true })
      .click();
    const editor = page.getByRole("form", {
      name: "Neue Aufgabe",
      exact: true,
    });
    await editor.getByLabel("Titel", { exact: true }).fill(title);
    const assignee = editor.getByRole("combobox", {
      name: "Zuständige Person",
      exact: true,
    });
    await expect(
      assignee.locator("option").filter({ hasText: "(ich)" }),
    ).toHaveCount(1);
    await assignee.selectOption({
      label: await assignee
        .locator("option")
        .filter({ hasText: "(ich)" })
        .textContent(),
    });
    await editor.getByLabel("Fällig am", { exact: true }).fill(due);
    await editor
      .getByLabel("Zurückgestellt bis", { exact: true })
      .fill(deferred);
    await editor
      .getByRole("button", { name: "Speichern", exact: true })
      .click();
    await expect(editor).toHaveCount(0);
    await page
      .getByRole("combobox", { name: "Ansicht", exact: true })
      .selectOption("mine");
    await expect(
      page.getByRole("heading", { name: title, exact: true }),
    ).toHaveCount(0);
    await page.getByLabel("Zurückgestellte anzeigen", { exact: true }).check();
    const row = page
      .locator(".tasks-results li")
      .filter({ has: page.getByRole("heading", { name: title, exact: true }) });
    await expect(row).toBeVisible();
    await row.getByRole("button", { name: "Bearbeiten", exact: true }).click();
    const edit = page.getByRole("form", {
      name: "Aufgabe bearbeiten",
      exact: true,
    });
    await expect(edit.getByLabel("Fällig am", { exact: true })).toHaveValue(
      due,
    );
    await expect(
      edit.getByLabel("Zurückgestellt bis", { exact: true }),
    ).toHaveValue(deferred);
    await edit.getByLabel("Zurückgestellt bis", { exact: true }).fill("");
    await edit
      .getByRole("combobox", { name: "Status", exact: true })
      .selectOption("done");
    await edit.getByRole("button", { name: "Speichern", exact: true }).click();
    await expect(edit).toHaveCount(0);
    await page
      .getByRole("combobox", { name: "Status", exact: true })
      .selectOption("done");
    await expect(row).toContainText("Erledigt");
    await row.getByRole("button", { name: "Bearbeiten", exact: true }).click();
    await expect(edit.getByLabel("Fällig am", { exact: true })).toHaveValue(
      due,
    );
    await expect(
      edit.getByLabel("Zurückgestellt bis", { exact: true }),
    ).toHaveValue("");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath(`${surface}-task-completed.png`),
      fullPage: false,
    });
    await context.close();
  });
}
