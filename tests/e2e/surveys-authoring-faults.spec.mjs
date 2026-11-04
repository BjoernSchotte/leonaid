import { test, expect } from "./csp-guard.mjs";
const baseURL = process.env.LEONAID_E2E_BASE_URL,
  token = process.env.SURVEY_ADMIN_SESSION;
if (!baseURL || !token) throw new Error("Survey member fixture required");
// The authoring steps stay in surveys-authoring.spec.mjs; publication does
// not depend on how the draft was written, so this draft comes from the
// Krapfentaxi template through the same creation page.
test("publication retries a lost acknowledgement", async ({ browser }) => {
  test.setTimeout(90000);
  const scenario = "Krapfentaxi";
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
    .fill(`${scenario} – Ihre Rückmeldung`);
  await page
    .getByLabel("Fragebogenvorlage", { exact: true })
    .selectOption("krapfentaxi");
  await page
    .getByRole("button", { name: "Umfrage erstellen", exact: true })
    .click();
  const editor = page.getByRole("region", { name: "Fragebogen bearbeiten" });
  await expect(editor).toBeVisible();
  await expect(page.locator("[data-draft-state]")).toHaveAttribute(
    "data-draft-state",
    "saved",
  );
  let lost = false;
  await page.route("**/api/v1/surveys/*/publish", async (route) => {
    if (!lost) {
      lost = true;
      await route.fetch();
      await route.abort("failed");
    } else await route.continue();
  });
  await editor
    .getByRole("button", { name: "Veröffentlichen", exact: true })
    .click();
  await expect(editor.getByRole("alert")).toContainText(
    "Veröffentlichung noch nicht bestätigt",
  );
  await editor
    .getByRole("button", {
      name: "Veröffentlichung erneut prüfen",
      exact: true,
    })
    .click();
  await expect(
    editor.getByText("Version 1 ist veröffentlicht.", { exact: true }),
  ).toBeVisible();
  const id = page.url().split("/").at(-1);
  const published = await page.evaluate(
    async (id) => (await fetch(`/api/v1/public/surveys/${id}`)).json(),
    id,
  );
  expect(published.number).toBe(1);
  expect(published.definition.title).toBe(`${scenario} – Ihre Rückmeldung`);
  await context.close();
});
