import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

const baseURL = process.env.LEONAID_E2E_BASE_URL;
const proof = process.env.LEONAID_E2E_ARTIFACT_DIR;
if (!baseURL || !proof) throw new Error("Survey fixture access is required");
const fixture = JSON.parse(
  readFileSync(`${proof}/raw-response-access.json`, "utf8"),
);

async function session(browser, token) {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1280, height: 900 },
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
  return context;
}
const detailURL = `${baseURL}/admin/surveys/${fixture.surveyId}?responseSelection=${fixture.snapshotId}&response=${fixture.participationId}`;

test("raw reader browses frozen responses and literal free text without aggregate access", async ({
  browser,
}) => {
  const context = await session(browser, fixture.readerToken);
  const page = await context.newPage();
  await page.goto(detailURL);
  const view = page.getByRole("region", {
    name: "Einzelantworten und Freitext",
    exact: true,
  });
  const individual = view.getByRole("region", {
    name: "Geöffnete Einzelantwort",
    exact: true,
  });
  await expect(individual).toContainText(fixture.literal);
  await expect(individual).toContainText("Alpha\nBeta");
  await expect(individual).toContainText(
    "Organisation: Gut\nVerpflegung: Verbesserungsbedarf",
  );
  await expect(view.locator(".surveys-analysis-applied")).toContainText(
    "51 Teilnahmen",
  );
  await expect(
    page.getByText("Antworten auswerten", { exact: true }),
  ).toHaveCount(0);
  await expect(view.getByLabel("Antwortquelle")).toHaveCount(0);
  await expect(individual.locator("img")).toHaveCount(0);
  expect(await page.evaluate(() => window.rawAnswerExecuted)).toBeUndefined();
  await individual.screenshot({
    path: `${proof}/surveys-responses-individual.png`,
    style: ".ui-topbar { position: static !important; }",
  });
  await view
    .getByRole("button", { name: "Weitere Antworten", exact: true })
    .click();
  await expect(view.locator(".surveys-response-list > li")).toHaveCount(1);
  await expect(
    view.getByRole("button", { name: "Antwort 51 ansehen" }),
  ).toBeVisible();
  await view
    .getByRole("button", { name: "Vorherige Antworten", exact: true })
    .click();
  await expect(view.locator(".surveys-response-list > li")).toHaveCount(50);
  const free = view.getByRole("region", {
    name: "Freitextantworten",
    exact: true,
  });
  await free
    .getByRole("button", { name: "Freitext laden", exact: true })
    .focus();
  await page.keyboard.press("Enter");
  await expect(free).toContainText("2 Freitextantworten");
  await expect(free).toContainText(fixture.literal);
  await expect(free.locator("img")).toHaveCount(0);
  await free
    .getByRole("listitem")
    .filter({ hasText: fixture.literal })
    .getByRole("button")
    .click();
  await expect(individual).toContainText(fixture.literal);
  await page.route(
    "**/response-selections/*/responses/*",
    (route) => route.abort("failed"),
    { times: 1 },
  );
  await free
    .getByRole("listitem")
    .filter({ hasText: "Saved partial feedback" })
    .getByRole("button")
    .click();
  await expect(view.getByRole("alert")).toContainText(
    "Die Anfrage konnte nicht bestätigt werden.",
  );
  await expect(individual).toHaveCount(0);
  await free
    .getByRole("listitem")
    .filter({ hasText: "Saved partial feedback" })
    .getByRole("button")
    .click();
  await expect(individual).toContainText("Saved partial feedback");
  await expect(individual).not.toContainText("Updated partial feedback");
  await page.reload();
  await expect(individual).toContainText("Saved partial feedback");
  await view.getByLabel("In Bearbeitung", { exact: true }).check();
  await view
    .getByRole("button", { name: "Antworten auswählen", exact: true })
    .click();
  await expect(view.locator(".surveys-analysis-applied")).toContainText(
    "52 Teilnahmen",
  );
  await free
    .getByRole("button", { name: "Freitext laden", exact: true })
    .click();
  await expect(free).toContainText("3 Freitextantworten");
  await expect(free).toContainText("Updated partial feedback");
  await view
    .getByLabel("Begonnen ab", { exact: true })
    .fill("2099-01-01T00:00");
  await view
    .getByRole("button", { name: "Antworten auswählen", exact: true })
    .click();
  await expect(view).toContainText(
    "Für diese Auswahl gibt es keine weiteren Antworten.",
  );
  await expect(view.locator(".surveys-analysis-applied")).toContainText(
    "0 Teilnahmen",
  );
  await view.getByLabel("Begonnen ab", { exact: true }).fill("");
  let originalBody;
  let stored;
  await page.route(
    `**/surveys/${fixture.surveyId}/response-selections`,
    async (route) => {
      originalBody = route.request().postDataJSON();
      const response = await route.fetch();
      expect(response.status()).toBe(200);
      stored = await response.json();
      await route.abort("failed");
    },
    { times: 1 },
  );
  await view
    .getByRole("button", { name: "Antworten auswählen", exact: true })
    .click();
  await expect(
    view.getByRole("button", { name: "Auswahl erneut anfordern" }),
  ).toBeVisible();
  const repeat = page.waitForRequest(
    (r) =>
      r.url().endsWith(`/surveys/${fixture.surveyId}/response-selections`) &&
      r.method() === "POST",
  );
  await view.getByRole("button", { name: "Auswahl erneut anfordern" }).click();
  expect((await repeat).postDataJSON()).toEqual(originalBody);
  await expect(view.locator(".surveys-analysis-applied")).toContainText(
    "52 Teilnahmen",
  );
  expect(new URL(page.url()).searchParams.get("responseSelection")).toBe(
    stored.id,
  );
  await free
    .getByRole("button", { name: "Freitext laden", exact: true })
    .click();
  await expect(free).toContainText(fixture.literal);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await free.screenshot({
    path: `${proof}/surveys-responses-mobile.png`,
    style: ".ui-topbar { position: static !important; }",
  });
  expect(await page.evaluate(() => window.rawAnswerExecuted)).toBeUndefined();
  await context.close();
});

test("aggregate-only member cannot navigate to individual responses or call raw endpoints", async ({
  browser,
}) => {
  const context = await session(browser, fixture.analystToken);
  const page = await context.newPage();
  await page.goto(detailURL);
  await expect(page.getByRole("alert")).toContainText(
    "Dieser Antwortstand ist für Sie nicht zugänglich.",
  );
  await expect(
    page.getByText("Antworten auswerten", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Einzelantworten lesen", { exact: true }),
  ).toHaveCount(0);
  await expect(page.locator(".surveys-responses")).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText(fixture.literal);
  const endpoint = `${baseURL}/api/v1/surveys/${fixture.surveyId}/response-selections`;
  for (const suffix of [
    "/versions",
    `/${fixture.snapshotId}`,
    `/${fixture.snapshotId}/responses`,
    `/${fixture.snapshotId}/responses/${fixture.participationId}`,
    `/${fixture.snapshotId}/free-text/text`,
  ]) {
    const response = await context.request.get(endpoint + suffix);
    expect(response.status()).toBe(404);
    expect(await response.text()).not.toContain(fixture.literal);
  }
  const create = await context.request.post(endpoint, {
    data: {
      operationId: "forged-raw-browser",
      filter: { versionId: fixture.versionId },
    },
  });
  expect(create.status()).toBe(404);
  const direct = await page.goto(
    `${endpoint}/${fixture.snapshotId}/responses/${fixture.participationId}`,
  );
  expect(direct.status()).toBe(404);
  await expect(page.locator("body")).not.toContainText(fixture.literal);
  await context.close();
});
