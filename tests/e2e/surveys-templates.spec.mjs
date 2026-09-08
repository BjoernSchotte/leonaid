import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

for (const [template, width] of [
  ["krapfentaxi", 1440],
  ["golf", 390],
]) {
  test(`create, edit and publish ${template} template without copying respondent data`, async ({
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
    const createdIds = [];
    try {
      for (let copy = 0; copy < 2; copy++) {
        await page.goto(`${baseURL}/admin/surveys/new`);
        await page
          .getByLabel("Titel der Umfrage", { exact: true })
          .fill(`Vorlage ${template} ${copy}`);
        await page
          .getByLabel("Fragebogenvorlage", { exact: true })
          .selectOption(template);
        await expect(
          page.locator("#survey-template-description"),
        ).toContainText("Drei Seiten");
        expect(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
        ).toBe(true);
        if (copy === 0)
          await page.screenshot({
            path: `${process.env.LEONAID_E2E_ARTIFACT_DIR}/surveys-template-${template}.png`,
            fullPage: true,
          });
        // First creation loses only the acknowledgement after the actual commit.
        if (copy === 0) {
          await page.route(
            "**/api/v1/surveys/*",
            async (route) => {
              if (route.request().method() !== "POST") return route.continue();
              await route.fetch();
              await route.abort("failed");
            },
            { times: 1 },
          );
        }
        await page
          .getByRole("button", { name: "Umfrage erstellen", exact: true })
          .click();
        if (copy === 0) {
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
        }
        const editor = page.getByRole("region", {
          name: "Fragebogen bearbeiten",
        });
        await expect(editor).toBeVisible();
        const sid = page.url().split("/").at(-1);
        createdIds.push(sid);
        const draft = await page.evaluate(
          async (id) => (await fetch(`/api/v1/surveys/${id}/draft`)).json(),
          sid,
        );
        expect(draft.revision).toBe(1);
        expect(draft.definition).toEqual({
          ...expected,
          title: `Vorlage ${template} ${copy}`,
        });
        const firstQuestion = () =>
          editor
            .getByRole("list", { name: "Fragen auf dieser Seite" })
            .locator("li")
            .first()
            .getByRole("button")
            .first();
        await firstQuestion().click();
        await editor
          .getByLabel("Fragetitel", { exact: true })
          .fill(`Eigene Frage ${copy}`);
        await expect(page.locator("[data-draft-state]")).toHaveAttribute(
          "data-draft-state",
          "saved",
        );
        await page.reload();
        await firstQuestion().click();
        await expect(
          editor.getByLabel("Fragetitel", { exact: true }),
        ).toHaveValue(`Eigene Frage ${copy}`);
        await editor
          .getByRole("button", { name: "Veröffentlichen", exact: true })
          .click();
        // Publication is asynchronous in the UI; poll the real endpoint to confirmation.
        await expect
          .poll(async () =>
            page.evaluate(
              async (id) =>
                (await fetch(`/api/v1/public/surveys/${id}`)).status,
              sid,
            ),
          )
          .toBe(200);
        const state = await page.evaluate(async (id) => {
          const version = await (
            await fetch(`/api/v1/public/surveys/${id}`)
          ).json();
          const response = await fetch(`/api/v1/surveys/${id}/analysis`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              operationId: "template-empty",
              filter: {
                versionId: version.id,
                statuses: ["in_progress", "partial", "completed"],
              },
            }),
          });
          return {
            version,
            status: response.status,
            analysis: await response.json(),
          };
        }, sid);
        expect(state.version.number).toBe(1);
        expect(state.version.definition.pages[0].elements[0].title).toBe(
          `Eigene Frage ${copy}`,
        );
        expect(state.status).toBe(200);
        expect(state.analysis.participationCount).toBe(0);
      }
      expect(new Set(createdIds).size).toBe(2);
    } finally {
      await context.close();
    }
  });
}
