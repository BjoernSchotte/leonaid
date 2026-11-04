import { test, expect } from "./csp-guard.mjs";
import { readFileSync } from "node:fs";

for (const [template, width] of [
  ["krapfentaxi", 1440],
  ["golf", 390],
]) {
  test(`create ${template} template survey after a lost creation acknowledgement`, async ({
    browser,
  }) => {
    const baseURL = process.env.LEONAID_E2E_BASE_URL;
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width, height: 900 },
    });
    await context.addCookies([
      {
        name: "__Host-leonaid_session",
        value: process.env.SURVEY_ADMIN_SESSION,
        url: baseURL,
        secure: true,
        httpOnly: true,
        sameSite: "Lax",
      },
    ]);
    const page = await context.newPage();
    const expected = JSON.parse(
      readFileSync(
        new URL(`../fixtures/surveys/${template}.json`, import.meta.url),
      ),
    );
    try {
      await page.goto(`${baseURL}/admin/surveys/new`);
      await page
        .getByLabel("Titel der Umfrage", { exact: true })
        .fill(`Vorlage ${template} lost acknowledgement`);
      await page
        .getByLabel("Fragebogenvorlage", { exact: true })
        .selectOption(template);
      // The creation loses only the acknowledgement after the actual commit.
      await page.route(
        "**/api/v1/surveys/*",
        async (route) => {
          if (route.request().method() !== "POST") return route.continue();
          await route.fetch();
          await route.abort("failed");
        },
        { times: 1 },
      );
      await page
        .getByRole("button", { name: "Umfrage erstellen", exact: true })
        .click();
      await expect(
        page.getByLabel("Fragebogenvorlage", { exact: true }),
      ).toBeDisabled();
      await expect(
        page.getByRole("button", {
          name: "Umfrage erstellen",
          exact: true,
        }),
      ).toBeEnabled();
      await page
        .getByRole("button", { name: "Umfrage erstellen", exact: true })
        .click();
      const editor = page.getByRole("region", {
        name: "Fragebogen bearbeiten",
      });
      await expect(editor).toBeVisible();
      const sid = page.url().split("/").at(-1);
      const draft = await page.evaluate(
        async (id) => (await fetch(`/api/v1/surveys/${id}/draft`)).json(),
        sid,
      );
      expect(draft.revision).toBe(1);
      expect(draft.definition).toEqual({
        ...expected,
        title: `Vorlage ${template} lost acknowledgement`,
      });
    } finally {
      await context.close();
    }
  });
}
