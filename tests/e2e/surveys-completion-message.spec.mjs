import { test, expect } from "@playwright/test";
import { randomUUID } from "node:crypto";
const baseURL = process.env.LEONAID_E2E_BASE_URL;
const admin = process.env.SURVEY_ADMIN_SESSION;
if (!baseURL || !admin) throw new Error("Real survey administrator required");
const firstText =
  "Danke für Ihre Hilfe!\nIhre Rückmeldung kommt dem nächsten Lions-Projekt zugute. 💛";
const nextText = "Vielen Dank aus der neuen Fragebogenversion.";
for (const width of [1440, 390]) {
  test(`published completion text remains version-bound at width ${width}`, async ({
    browser,
    request,
  }) => {
    const surveyId = randomUUID();
    const path = `${baseURL}/api/v1/surveys/${surveyId}`;
    const auth = { Cookie: `__Host-leonaid_session=${admin}` };
    const definition = (text) => ({
      title: "Rückmeldung zum Abschluss",
      completedHtml: text,
      pages: [
        {
          name: "one",
          elements: [
            {
              type: "text",
              name: "answer",
              title: "Ihre Rückmeldung",
              isRequired: true,
            },
          ],
        },
      ],
    });
    async function write(suffix, body, method = "post") {
      const result = await request[method](path + suffix, {
        headers: auth,
        data: body,
        ignoreHTTPSErrors: true,
      });
      expect(result.status()).toBe(200);
      return result.json();
    }
    await write("", {
      operationId: randomUUID(),
      title: "Abschlusstext",
      definition: definition(firstText),
    });
    await write("/publish", { operationId: randomUUID(), expectedRevision: 1 });
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width, height: 900 },
    });
    try {
      const page = await context.newPage();
      await page.goto(`${baseURL}/surveys/${surveyId}`);
      await page.getByRole("button", { name: "Umfrage beginnen" }).click();
      await page
        .getByRole("textbox", { name: /Ihre Rückmeldung/ })
        .fill("Ein gutes Projekt");
      await expect(page.locator("[data-save-state]")).toHaveAttribute(
        "data-save-state",
        "saved",
      );
      const pid = new URL(page.url()).searchParams.get("participation");
      expect(pid).toBeTruthy();
      const endpoint = `/api/v1/public/surveys/${surveyId}/participations/${pid}`;
      const before = await page.evaluate(
        async (url) => (await fetch(url)).json(),
        endpoint,
      );
      await write(
        "/draft",
        {
          operationId: randomUUID(),
          expectedRevision: 2,
          definition: definition(nextText),
        },
        "put",
      );
      await write("/publish", {
        operationId: randomUUID(),
        expectedRevision: 3,
      });
      await page
        .getByRole("button", { name: "Abschließen", exact: true })
        .click();
      const message = page.locator(".survey-completion-message");
      await expect(message).toHaveText(firstText);
      await expect(message).toHaveCSS("white-space", "pre-wrap");
      const writes = [];
      page.on("request", (r) => {
        if (["POST", "PUT", "PATCH"].includes(r.method()))
          writes.push(r.method());
      });
      await page.reload();
      await expect(message).toHaveText(firstText);
      expect(writes).toEqual([]);
      const completed = await page.evaluate(
        async (url) => (await fetch(url)).json(),
        endpoint,
      );
      expect(completed.version.id).toBe(before.version.id);
      expect(completed.response.status).toBe("completed");
      expect(completed.response.answers).toEqual({
        answer: "Ein gutes Projekt",
      });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: `${process.env.LEONAID_E2E_ARTIFACT_DIR}/surveys-branding-completion-${width}.png`,
        fullPage: true,
      });
      await page.goto(`${baseURL}/surveys/${surveyId}`);
      await page.getByRole("button", { name: "Umfrage beginnen" }).click();
      await page
        .getByRole("textbox", { name: /Ihre Rückmeldung/ })
        .fill("Neue Teilnahme");
      await page
        .getByRole("button", { name: "Abschließen", exact: true })
        .click();
      await expect(message).toHaveText(nextText);
    } finally {
      await context.close();
    }
  });
}
