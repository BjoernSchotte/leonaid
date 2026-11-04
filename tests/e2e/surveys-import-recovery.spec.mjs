import { test, expect } from "./csp-guard.mjs";
import { readFile } from "node:fs/promises";

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
async function exported(page, button) {
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: button, exact: true }).click();
  return JSON.parse(await readFile(await (await download).path(), "utf8"));
}

test("JSON import preserves unknown data and stable IDs while unsafe publication is rejected", async ({
  browser,
}) => {
  test.setTimeout(90000);
  const { context, page, read } = await create(browser, "Import test");
  const initial = await read();
  await page
    .getByText("JSON importieren / exportieren", { exact: true })
    .click();
  const input = page.getByRole("textbox", {
    name: "Fragebogen-JSON",
    exact: true,
  });
  const apply = page.getByRole("button", {
    name: "JSON übernehmen",
    exact: true,
  });
  await input.fill("{broken");
  await apply.click();
  await expect(page.getByRole("alert")).toContainText("JSON ist ungültig");
  expect(await read()).toEqual(initial);
  await input.fill("null");
  await apply.click();
  await expect(page.getByRole("alert")).toContainText("als Objekt");
  expect(await read()).toEqual(initial);
  const imported = {
    title: "Imported questionnaire",
    metadata: { keep: [1, "ä", { future: true }] },
    pages: [
      {
        name: "stable_page",
        elements: [
          {
            type: "text",
            name: "stable_question",
            title: "Keep me",
            futureOption: { enabled: true },
          },
        ],
      },
    ],
  };
  await page.getByLabel("JSON-Datei öffnen", { exact: true }).setInputFiles({
    name: "example.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(imported)),
  });
  await apply.click();
  await state(page, "saved");
  expect((await read()).definition).toEqual(imported);
  await expect(
    page.getByRole("region", { name: "Kompatibilitätshinweise" }),
  ).toContainText("pages[0].elements[0].futureOption");
  await page
    .getByRole("button", { name: "Kurzer Text Keep me", exact: true })
    .click();
  await expect(page.getByLabel("Fragetitel", { exact: true })).toHaveCount(0);
  await page
    .getByLabel("Titel des Fragebogens", { exact: true })
    .fill("Edited title");
  imported.title = "Edited title";
  await state(page, "saved");
  expect((await read()).definition).toEqual(imported);
  expect(await exported(page, "Fragebogen als JSON exportieren")).toEqual(
    imported,
  );
  await page
    .getByRole("button", { name: "Veröffentlichen", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("definition.metadata");
  delete imported.metadata;
  await input.fill(JSON.stringify(imported));
  await apply.click();
  await state(page, "saved");
  await page
    .getByRole("button", { name: "Veröffentlichen", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("elements[0]");
  delete imported.pages[0].elements[0].futureOption;
  imported.pages[0].elements[0].description =
    "<img src=https://invalid.example/unsafe>";
  await input.fill(JSON.stringify(imported));
  await apply.click();
  await state(page, "saved");
  let external = 0;
  page.on("request", (request) => {
    if (request.url().includes("invalid.example")) external++;
  });
  await page.getByRole("button", { name: "Vorschau", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("description");
  await expect(
    page.getByRole("region", { name: "Fragebogen-Vorschau" }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Veröffentlichen", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("elements[0]");
  expect(external).toBe(0);
  imported.pages[0].elements[0].description = "Plain description";
  await input.fill(JSON.stringify(imported));
  await apply.click();
  await state(page, "saved");
  await page.getByRole("button", { name: "Rückgängig", exact: true }).click();
  await state(page, "saved");
  expect((await read()).definition.pages[0].elements[0].description).toContain(
    "<img",
  );
  await page.getByRole("button", { name: "Wiederholen", exact: true }).click();
  await state(page, "saved");
  await page.reload();
  await expect(
    page.getByLabel("Titel des Fragebogens", { exact: true }),
  ).toHaveValue(imported.title);
  expect((await read()).definition).toEqual(imported);
  await page
    .getByRole("button", { name: "Veröffentlichen", exact: true })
    .click();
  await expect(
    page.getByText("Version 1 ist veröffentlicht.", { exact: true }),
  ).toBeVisible();
  await context.close();
});

test("undo and two-tab conflict preserve explicit saved state", async ({
  browser,
}) => {
  test.setTimeout(90000);
  const { context, page, read } = await create(browser, "Recovery test");
  const title = page.getByLabel("Titel des Fragebogens", { exact: true });
  await title.fill("First accepted edit");
  // The autosave runs after input; wait for the stored draft, not a stale "saved".
  await expect
    .poll(async () => (await read()).definition.title)
    .toBe("First accepted edit");
  await state(page, "saved");
  await title.fill("Newer local edit");
  await expect
    .poll(async () => (await read()).definition.title)
    .toBe("Newer local edit");
  await state(page, "saved");
  await page.getByRole("button", { name: "Rückgängig", exact: true }).click();
  await state(page, "saved");
  expect((await read()).definition.title).toBe("First accepted edit");
  await page.getByRole("button", { name: "Wiederholen", exact: true }).click();
  await state(page, "saved");
  expect((await read()).definition.title).toBe("Newer local edit");
  const second = await context.newPage();
  await second.goto(page.url());
  const secondTitle = second.getByLabel("Titel des Fragebogens", {
    exact: true,
  });
  await expect(secondTitle).toHaveValue("Newer local edit");
  await title.fill("Latest server edit");
  await state(page, "saved");
  await secondTitle.fill("Conflicting local edit");
  await state(second, "conflict");
  expect((await read()).definition.title).toBe("Latest server edit");
  const local = await exported(
    second,
    "Lokale Änderungen als JSON exportieren",
  );
  expect(local.title).toBe("Conflicting local edit");
  await second
    .getByRole("button", {
      name: "Serverstand laden und lokale Änderungen verwerfen",
      exact: true,
    })
    .click();
  await state(second, "saved");
  await expect(secondTitle).toHaveValue("Latest server edit");
  await secondTitle.fill("Resolved edit");
  await state(second, "saved");
  expect((await read()).definition.title).toBe("Resolved edit");
  await context.close();
});
