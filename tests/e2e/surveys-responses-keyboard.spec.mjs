import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./csp-guard.mjs";
import { readFileSync } from "node:fs";

// Runs in the survey analysis stack (tools/surveys/infrastructure.sh): the
// raw-response fixture with 51 responses for a reader with read_responses.
const baseURL = process.env.LEONAID_E2E_BASE_URL;
const proof = process.env.LEONAID_E2E_ARTIFACT_DIR;
if (!baseURL || !proof) throw new Error("Survey fixture access is required");
const fixture = JSON.parse(
  readFileSync(`${proof}/raw-response-access.json`, "utf8"),
);

async function expectNoSeriousAccessibilityViolations(page, label) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(
    result.violations
      .filter((v) => v.impact === "critical" || v.impact === "serious")
      .map((v) => `${label}: ${v.id}`),
  ).toEqual([]);
}

test("response list: j/k, Enter, Esc, x and a read-only status by keyboard", async ({
  browser,
}) => {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1440, height: 1000 },
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: fixture.readerToken,
      url: baseURL,
      secure: true,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await page.goto(
      `${baseURL}/admin/surveys/${fixture.surveyId}/responses?responseSelection=${fixture.snapshotId}`,
    );
    await expect(
      page.getByRole("heading", { level: 1, name: "Einzelantworten" }),
    ).toBeVisible();
    const rows = page.locator(".listview .row-link");
    await expect(rows).toHaveCount(51);
    // Status is a fact of the participation: no letter key, no chip menu.
    await expect(page.locator(".list-hint")).not.toContainText("Status");
    await expect(page.locator('[data-chip="status"]')).toHaveCount(0);
    await expectNoSeriousAccessibilityViolations(page, "Einzelantworten");
    await page.locator("body").click({ position: { x: 5, y: 5 } });

    await page.keyboard.press("j");
    await page.keyboard.press("j");
    await page.keyboard.press("k");
    await expect(rows.first()).toBeFocused();
    await page.keyboard.press("Enter");
    const pane = page.getByRole("complementary", {
      name: "Details: Antwort 1",
    });
    await expect(pane).toBeVisible();
    await expect(pane.locator(".svr-answers")).toBeVisible();
    await expect(page).toHaveURL(/[?&]open=[0-9a-f-]{36}/);
    await expect(pane.locator(".pane-props")).toHaveCount(0);
    await expectNoSeriousAccessibilityViolations(page, "Antwort im Detail");

    // j in the open pane shows the next response.
    await page.keyboard.press("j");
    await expect(rows.nth(1)).toBeFocused();
    await expect(
      page.getByRole("complementary", { name: "Details: Antwort 2" }),
    ).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.locator(".pane")).toHaveCount(0);
    await expect(rows.nth(1)).toBeFocused();
    await expect(page).not.toHaveURL(/[?&]open=/);

    // x checks rows; s edits nothing; Esc clears the selection.
    await page.keyboard.press("x");
    await page.keyboard.press("j");
    await page.keyboard.press("x");
    const bulk = page.getByRole("region", { name: "Auswahl" });
    await expect(bulk).toContainText("2 ausgewählt");
    await expect(bulk.getByRole("button", { name: /Status/ })).toHaveCount(0);
    await page.keyboard.press("s");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.keyboard.press("Escape");
    await expect(bulk).toHaveCount(0);

    // The palette offers the page's own commands.
    await page.keyboard.press("Control+k");
    const palette = page.getByRole("dialog", { name: "Befehlspalette" });
    await expect(palette).toBeVisible();
    await page.keyboard.type("Freitextantworten ansehen");
    await page.keyboard.press("Enter");
    const free = page.getByRole("dialog", { name: "Freitextantworten" });
    await expect(free).toContainText("2 Freitextantworten");
    await expectNoSeriousAccessibilityViolations(page, "Freitextantworten");
    await page.keyboard.press("Escape");
    await expect(free).toHaveCount(0);
    await page.screenshot({
      path: `${proof}/surveys-responses-keyboard.png`,
      fullPage: false,
    });
    expect(pageErrors).toEqual([]);
  } finally {
    await context.close();
  }
});
