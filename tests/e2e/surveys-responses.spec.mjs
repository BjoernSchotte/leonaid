import { expect, screenshotWithStaticTopbar, test } from "./csp-guard.mjs";
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
// The survey page's link from before the list view: `response=` is the old
// name of the open response.
const detailURL = `${baseURL}/admin/surveys/${fixture.surveyId}?responseSelection=${fixture.snapshotId}&response=${fixture.participationId}`;
const responsesURL = `${baseURL}/admin/surveys/${fixture.surveyId}/responses`;

async function chooseSelection(page, change) {
  await page
    .getByRole("button", { name: "Antwortstand wählen", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "Antwortstand wählen" });
  await expect(dialog).toBeVisible();
  await change(dialog);
  await dialog
    .getByRole("button", { name: "Antworten auswählen", exact: true })
    .click();
  await expect(dialog).toHaveCount(0);
}

test("raw reader browses frozen responses and literal free text without aggregate access", async ({
  browser,
}) => {
  const context = await session(browser, fixture.readerToken);
  const page = await context.newPage();
  await page.goto(detailURL);
  const link = page.getByRole("link", {
    name: "Einzelantworten lesen",
    exact: true,
  });
  await expect(link).toHaveAttribute(
    "href",
    `/admin/surveys/${fixture.surveyId}/responses?responseSelection=${fixture.snapshotId}&open=${fixture.participationId}`,
  );
  await expect(
    page.getByText("Antworten auswerten", { exact: true }),
  ).toHaveCount(0);
  await link.click();

  await expect(
    page.getByRole("heading", { level: 1, name: "Einzelantworten" }),
  ).toBeVisible();
  const pane = page.getByRole("complementary", { name: /^Details: Antwort / });
  await expect(pane).toContainText(fixture.literal);
  await expect(pane).toContainText("Alpha\nBeta");
  await expect(pane).toContainText(
    "Organisation: Gut\nVerpflegung: Verbesserungsbedarf",
  );
  await expect(pane.locator("img")).toHaveCount(0);
  await expect(page.locator(".svr-applied")).toContainText("51 Teilnahmen");
  await expect(page.locator(".page-count")).toHaveText("51 Antworten");
  await expect(page.locator(".listview .rows > li")).toHaveCount(51);
  await expect(
    page.locator(`[data-response-row="${fixture.participationId}"]`),
  ).toBeVisible();
  expect(await page.evaluate(() => window.rawAnswerExecuted)).toBeUndefined();
  await screenshotWithStaticTopbar(pane, {
    path: `${proof}/surveys-responses-individual.png`,
  });

  // Free text opens the response it belongs to.
  await page.getByRole("button", { name: "Freitexte", exact: true }).click();
  const free = page.getByRole("dialog", { name: "Freitextantworten" });
  await expect(free).toContainText("2 Freitextantworten");
  await expect(free).toContainText(fixture.literal);
  await expect(free.locator("img")).toHaveCount(0);
  await free
    .getByRole("listitem")
    .filter({ hasText: "Saved partial feedback" })
    .getByRole("button", { name: "Zugehörige Einzelantwort ansehen" })
    .click();
  await expect(free).toHaveCount(0);
  await expect(pane).toContainText("Saved partial feedback");
  await expect(pane).toContainText("Teilantwort");
  await expect(pane).not.toContainText("Updated partial feedback");
  await page.reload();
  await expect(pane).toContainText("Saved partial feedback");

  // A new selection includes the response in progress and its newer text.
  await chooseSelection(page, async (dialog) => {
    await expect(dialog.getByLabel("Antwortquelle")).toHaveCount(0);
    await dialog.getByLabel("In Bearbeitung", { exact: true }).check();
  });
  await expect(page.locator(".svr-applied")).toContainText("52 Teilnahmen");
  await expect(pane).toHaveCount(0);
  await expect(page).not.toHaveURL(/[?&]open=/);
  await page.getByRole("button", { name: "Freitexte", exact: true }).click();
  await expect(free).toContainText("3 Freitextantworten");
  await expect(free).toContainText("Updated partial feedback");
  await page.keyboard.press("Escape");
  await expect(free).toHaveCount(0);

  await chooseSelection(page, async (dialog) => {
    await dialog
      .getByLabel("Begonnen ab", { exact: true })
      .fill("2099-01-01T00:00");
  });
  await expect(page.locator(".svr-applied")).toContainText("0 Teilnahmen");
  await expect(
    page.getByRole("heading", { name: "Noch keine Antworten" }),
  ).toBeVisible();

  await chooseSelection(page, async (dialog) => {
    await dialog.getByLabel("Begonnen ab", { exact: true }).fill("");
  });
  await expect(page.locator(".svr-applied")).toContainText("52 Teilnahmen");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({ path: `${proof}/surveys-responses-mobile.png` });
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
  await expect(page.locator("body")).not.toContainText(fixture.literal);

  // The page itself asks nothing of the raw endpoints for this account.
  const raw = [];
  page.on("request", (request) => {
    if (request.url().includes("/response-selections")) raw.push(request.url());
  });
  await page.goto(
    `${responsesURL}?responseSelection=${fixture.snapshotId}&open=${fixture.participationId}`,
  );
  await expect(page.getByRole("alert")).toContainText(
    "Dieser Antwortstand ist für Sie nicht zugänglich.",
  );
  await expect(page.locator(".listview")).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText(fixture.literal);
  expect(raw).toEqual([]);

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
