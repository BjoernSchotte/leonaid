import { test, expect } from "./csp-guard.mjs";

const baseURL = process.env.LEONAID_E2E_BASE_URL;
const token = process.env.SURVEY_ADMIN_SESSION;
if (!baseURL || !token) throw new Error("Survey member fixture required");

async function create(browser, title) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
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
  await page.getByLabel("Titel der Umfrage", { exact: true }).fill(title);
  await page
    .getByRole("button", { name: "Umfrage erstellen", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Fragebogen bearbeiten" }),
  ).toBeVisible();
  const id = page.url().split("/").at(-1);
  const read = () =>
    page.evaluate(
      async (id) => (await fetch(`/api/v1/surveys/${id}/draft`)).json(),
      id,
    );
  return { context, page, id, read };
}
const state = (page, value) =>
  expect(page.locator("[data-draft-state]")).toHaveAttribute(
    "data-draft-state",
    value,
  );
test("lost draft acknowledgement and undo preserve explicit saved state", async ({
  browser,
}) => {
  test.setTimeout(90000);
  const { context, page, read } = await create(browser, "Recovery test");
  const title = page.getByLabel("Titel des Fragebogens", { exact: true });
  const requests = [];
  let disconnected = true;
  await page.route("**/api/v1/surveys/*/draft", async (route) => {
    if (route.request().method() !== "PUT") return route.continue();
    requests.push(route.request().postDataJSON());
    if (requests.length === 1) {
      await route.fetch();
      return route.abort("failed");
    }
    if (disconnected) return route.abort("failed");
    return route.continue();
  });
  await title.fill("First accepted edit");
  await state(page, "error");
  expect((await read()).definition.title).toBe("First accepted edit");
  await title.fill("Newer local edit");
  await state(page, "error");
  expect((await read()).definition.title).toBe("First accepted edit");
  disconnected = false;
  await page
    .getByRole("button", { name: "Jetzt speichern", exact: true })
    .click();
  await state(page, "saved");
  expect(requests[1]).toEqual(requests[0]);
  expect(requests[2]).toEqual(requests[0]);
  expect(requests.at(-1).expectedRevision).toBe(
    requests[0].expectedRevision + 1,
  );
  expect((await read()).definition.title).toBe("Newer local edit");
  await page.getByRole("button", { name: "Rückgängig", exact: true }).click();
  await state(page, "saved");
  expect((await read()).definition.title).toBe("First accepted edit");
  await page.getByRole("button", { name: "Wiederholen", exact: true }).click();
  await state(page, "saved");
  expect((await read()).definition.title).toBe("Newer local edit");
  await context.close();
});
