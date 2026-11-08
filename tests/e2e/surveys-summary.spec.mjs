import { analyzeAccessibility } from "./axe.mjs";
import { expect, test } from "./csp-guard.mjs";
import { readFileSync } from "node:fs";

// Survey evaluation (Task 5.6b) in the analysis stack: 30 participations
// seeded by tools/surveys/summary_live.py, a raw reader and an aggregate-only
// member. Counts are disclosed with k = 5 on the server.
const baseURL = process.env.LEONAID_E2E_BASE_URL;
const proof = process.env.LEONAID_E2E_ARTIFACT_DIR;
if (!baseURL || !proof) throw new Error("Survey fixture access is required");
const fixture = JSON.parse(
  readFileSync(`${proof}/summary-access.json`, "utf8"),
);
const surveyPath = `/admin/surveys/${fixture.surveyId}`;
const summaryURL = `${baseURL}${surveyPath}/responses/summary`;

async function session(
  browser,
  token,
  viewport = { width: 1440, height: 1000 },
) {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport,
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

async function noSeriousAxe(page, label) {
  const result = await analyzeAccessibility(page);
  expect(
    result.violations
      .filter((v) => v.impact === "critical" || v.impact === "serious")
      .map((v) => `${label}: ${v.id}`),
  ).toEqual([]);
}

const panel = (page, title) =>
  page.locator(".svs-panel").filter({
    has: page.getByRole("heading", { name: new RegExp(`\\d+\\. ${title}`) }),
  });

test("reader: charts, withheld counts, quotes and answer columns", async ({
  browser,
}) => {
  const context = await session(browser, fixture.readerToken);
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    // The survey page leads to the evaluation.
    await page.goto(`${baseURL}${surveyPath}`);
    await expect(
      page.getByRole("link", { name: "Auswertung ansehen", exact: true }),
    ).toHaveAttribute("href", `${surveyPath}/responses/summary`);
    await page.goto(`${summaryURL}?responseSelection=${fixture.snapshotId}`);
    await expect(
      page.getByRole("heading", { level: 1, name: "Auswertung" }),
    ).toBeVisible();
    await expect(page.locator(".page-count")).toHaveText("30 Teilnahmen");
    const sections = page.getByRole("navigation", { name: "Antworten" });
    await expect(
      sections.getByRole("link", { name: "Auswertung" }),
    ).toHaveAttribute("aria-current", "page");

    // Choice: Meter bars as in the prototype, largest first.
    const gate = panel(page, "Haben Sie beim Ausliefern geholfen\\?");
    await expect(gate.locator(".bars li").first()).toContainText("Ja");
    await expect(gate.locator(".bars li").first()).toContainText("18 (60 %)");

    // NPS: scores of 2-3 people are withheld, so is every score below 10,
    // and with them the NPS score and the segments (disclosure R1, R3).
    const nps = panel(page, "Wie wahrscheinlich");
    await expect(nps.locator(".answer-avg .num")).toHaveText("–");
    await expect(nps.getByRole("list", { name: /^Legende/ })).toHaveCount(0);
    const canvases = nps.locator("canvas[role=img]");
    await expect(canvases).toHaveCount(1);
    await expect(canvases.first()).toHaveAttribute("aria-label", /3: –/);
    await expect(canvases.first()).toHaveAttribute(
      "aria-label",
      /10: 10 \(33 %\)/,
    );
    await nps.getByText("Als Tabelle anzeigen").click();
    await expect(nps.getByRole("table")).toContainText("–");

    // Matrix: a row whose cells would reveal each other shows both withheld.
    const matrix = panel(page, "Bewertung");
    await expect(matrix.locator("canvas[role=img]")).toHaveAttribute(
      "aria-label",
      /Verpflegung Gut –, Verbesserungsbedarf –/,
    );
    // Free text: quotes for readers, rendered as text.
    const quotes = panel(page, "Was sollten wir anders machen\\?");
    await expect(quotes.locator(".answer-texts li").first()).toBeVisible();
    await expect(quotes.locator("img")).toHaveCount(0);
    await noSeriousAxe(page, "Auswertung hell");
    await page.screenshot({
      path: `${proof}/surveys-responses-summary-desktop.png`,
      fullPage: true,
    });

    // A theme switch redraws the charts without reload (tokens via CSSOM).
    await page.evaluate(() =>
      document.documentElement.setAttribute("data-theme", "dark"),
    );
    await expect(canvases.first()).toBeVisible();
    await noSeriousAxe(page, "Auswertung dunkel");
    await page.evaluate(() =>
      document.documentElement.setAttribute("data-theme", "light"),
    );

    // "Alle … Freitexte" opens the dialog on that question in the list.
    await quotes
      .getByRole("link", { name: /^Alle \d+ Freitexte ansehen$/ })
      .click();
    const dialog = page.getByRole("dialog", { name: "Freitextantworten" });
    await expect(dialog).toContainText("12 Freitextantworten");
    await page.keyboard.press("Escape");
    await expect(page).not.toHaveURL(/freeText=/);
    // Answer columns: chosen options in the rows (never free text).
    await expect(page.locator(".listview .row-link").first()).toContainText(
      /Ja|Nein/,
    );
    await expect(page.locator(".listview")).not.toContainText("Packstation");

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${summaryURL}?responseSelection=${fixture.snapshotId}`);
    await expect(page.locator(".svs-panel").first()).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `${proof}/surveys-responses-summary-mobile.png`,
      fullPage: true,
    });
    expect(await page.evaluate(() => window.summaryExecuted)).toBeUndefined();
    expect(errors).toEqual([]);
  } finally {
    await context.close();
  }
});

test("aggregate-only: charts without quotes, no list, whole past days", async ({
  browser,
}) => {
  const context = await session(browser, fixture.analystToken);
  const page = await context.newPage();
  try {
    await page.goto(`${baseURL}${surveyPath}`);
    await expect(
      page.getByRole("link", { name: "Auswertung ansehen", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Einzelantworten lesen", { exact: true }),
    ).toHaveCount(0);
    await page.goto(summaryURL);
    await expect(
      page.getByRole("navigation", { name: "Antworten" }),
    ).toHaveCount(0);
    const form = page.locator(".svr-form");
    await expect(form).toContainText("ganze Tage");
    await expect(
      form.getByLabel("Begonnen ab", { exact: true }),
    ).toHaveAttribute("type", "date");
    // A start today selects nothing: whole days up to yesterday only.
    // "Today" is the club's day (Europe/Berlin), which the API judges, not
    // the browser's UTC day: from 00:00 to 01:00 Berlin that is yesterday,
    // a whole past day. A minute ahead keeps it today (or later) for the
    // API even when midnight passes before the request.
    const day = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Europe/Berlin",
    }).format(new Date(Date.now() + 60_000));
    await form.getByLabel("Begonnen ab", { exact: true }).fill(day);
    await form.getByRole("button", { name: "Antworten auswählen" }).click();
    await expect(form.getByRole("alert")).toContainText(
      "nur ganze Tage bis gestern",
    );
    await form.getByLabel("Begonnen ab", { exact: true }).fill("");
    await form.getByRole("button", { name: "Antworten auswählen" }).click();
    await expect(page.locator(".page-count")).toHaveText("30 Teilnahmen");
    const quotes = panel(page, "Was sollten wir anders machen\\?");
    await expect(quotes).toContainText("Antworten (Freitext)");
    await expect(quotes.locator(".answer-texts")).toHaveCount(0);
    await expect(quotes.getByRole("link")).toHaveCount(0);
    await expect(page.locator("body")).not.toContainText("Packstation");
    await expect(
      panel(page, "Wie wahrscheinlich").locator("canvas"),
    ).toHaveCount(1);
    await page.goto(`${baseURL}${surveyPath}/responses`);
    await expect(page.getByRole("alert")).toContainText(
      "Die Einzelantworten dieser Umfrage sind für Sie nicht zugänglich.",
    );
  } finally {
    await context.close();
  }
});
