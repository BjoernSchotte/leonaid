import { test, expect } from "@playwright/test";
import { writeFileSync } from "node:fs";
const baseURL = process.env.LEONAID_E2E_BASE_URL;
const proof = process.env.LEONAID_E2E_ARTIFACT_DIR;
async function session(browser, token, mobile = false) {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    timezoneId: "UTC",
    viewport: mobile
      ? { width: 390, height: 844 }
      : { width: 1440, height: 1000 },
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
test("member manages lifecycle and timeout through the real module", async ({
  browser,
}) => {
  const context = await session(browser, process.env.SURVEY_ADMIN_SESSION);
  const page = await context.newPage();
  await page.goto(`${baseURL}/admin/`);
  await page
    .getByRole("navigation", { name: "Hauptnavigation" })
    .first()
    .getByRole("link", { name: "Umfragen", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Umfragen", exact: true }),
  ).toBeVisible();
  await page.getByText("Standard für Teilantworten", { exact: true }).click();
  await page.getByLabel("Standardzeitraum in Sekunden").fill("25");
  await page
    .getByRole("button", { name: "Standard speichern", exact: true })
    .click();
  await expect(
    page.getByText("Standard wurde gespeichert.", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("Standardzeitraum in Sekunden").fill("1800");
  await page
    .getByRole("button", { name: "Standard speichern", exact: true })
    .click();
  await expect
    .poll(() =>
      page.evaluate(
        async () =>
          (await (await fetch("/api/v1/survey-settings")).json())
            .inactivityTimeoutSeconds,
      ),
    )
    .toBe(1800);
  await page.getByRole("link", { name: "Neue Umfrage", exact: true }).click();
  await page
    .getByLabel("Titel der Umfrage", { exact: true })
    .fill("Feedback aus der Lions-Aktion");
  await page
    .getByRole("combobox", { name: "Zuordnung", exact: true })
    .selectOption(process.env.SURVEY_ACTION_ID);
  await page
    .getByRole("button", { name: "Umfrage erstellen", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Fragebogen bearbeiten" }),
  ).toBeVisible();
  const id = page.url().split("/").at(-1);
  await page.getByText("Geplantes Ende", { exact: true }).click();
  const future = new Date(Date.now() + 86400000).toISOString().slice(0, 16);
  await page.getByLabel("Teilnahme endet am", { exact: true }).fill(future);
  await page
    .getByRole("button", { name: "Geplantes Ende speichern", exact: true })
    .click();
  await expect(
    page.getByText("Geplantes Ende wurde gespeichert.", { exact: true }),
  ).toBeVisible();
  const scheduled = await page.evaluate(
    async (key) =>
      (await (await fetch(`/api/v1/surveys/${key}`)).json()).endsAt,
    id,
  );
  expect(new Date(scheduled).toISOString().slice(0, 16)).toBe(future);
  await page.reload();
  await page.getByText("Geplantes Ende", { exact: true }).click();
  await expect(
    page.getByLabel("Teilnahme endet am", { exact: true }),
  ).toHaveValue(future);
  await page.getByLabel("Teilnahme endet am", { exact: true }).fill("");
  await page
    .getByRole("button", { name: "Geplantes Ende speichern", exact: true })
    .click();
  await expect
    .poll(() =>
      page.evaluate(
        async (key) =>
          (await (await fetch(`/api/v1/surveys/${key}`)).json()).endsAt,
        id,
      ),
    )
    .toBeNull();
  await page
    .getByText("Teilantworten nach Inaktivität", { exact: true })
    .click();
  await page.getByLabel("Abweichender Zeitraum in Sekunden").fill("3");
  await page
    .getByRole("button", { name: "Zeitraum speichern", exact: true })
    .click();
  await expect(
    page.getByText("Zeitraum wurde gespeichert.", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Veröffentlichen", exact: true })
    .click();
  const state = page.locator("[data-survey-status]");
  await expect(state).toHaveAttribute("data-survey-status", "active");
  const publicPage = await context.newPage();
  await publicPage.goto(`${baseURL}/surveys/${id}`);
  await expect(
    publicPage.getByRole("button", { name: "Umfrage beginnen", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Teilnahme beenden", exact: true })
    .click();
  await expect(state).toHaveAttribute("data-survey-status", "ended");
  await page.getByRole("button", { name: "Archivieren", exact: true }).click();
  await expect(state).toHaveAttribute("data-survey-status", "archived");
  await page
    .getByRole("button", { name: "In Papierkorb verschieben", exact: true })
    .click();
  await page
    .getByRole("button", {
      name: "Jetzt in Papierkorb verschieben",
      exact: true,
    })
    .click();
  await expect(state).toHaveAttribute("data-survey-status", "deleted");
  await page
    .getByRole("button", { name: "Wiederherstellen", exact: true })
    .click();
  await expect(state).toHaveAttribute("data-survey-status", "ended");
  await page.reload();
  await expect(state).toHaveAttribute("data-survey-status", "ended");
  await expect(
    page.getByRole("region", { name: "Fragebogen bearbeiten" }),
  ).toHaveCount(0);
  expect(
    await page.evaluate(
      async (sid) => (await fetch(`/api/v1/public/surveys/${sid}`)).status,
      id,
    ),
  ).toBe(409);
  await publicPage.reload();
  await expect(
    publicPage.getByRole("button", { name: "Umfrage beginnen", exact: true }),
  ).toHaveCount(0);
  await page.screenshot({
    path: `${proof}/surveys-module-lifecycle.png`,
    fullPage: true,
  });
  await page.getByRole("link", { name: "Alle Umfragen", exact: false }).click();
  await page
    .getByLabel("Umfrage suchen", { exact: true })
    .fill("Feedback aus der Lions-Aktion");
  await page
    .getByRole("combobox", { name: "Status", exact: true })
    .selectOption("ended");
  await expect(page.locator(".surveys-list li")).toHaveCount(1);
  await expect(page.locator(".surveys-list")).toContainText("Beendet");
  writeFileSync(
    `${proof}/module-result.json`,
    JSON.stringify({ id, actionId: process.env.SURVEY_ACTION_ID }),
  );
  await context.close();
});

test("designer sees scoped surveys without publish or delete controls on mobile", async ({
  browser,
}) => {
  const context = await session(
    browser,
    process.env.SURVEY_DESIGN_SESSION,
    true,
  );
  const page = await context.newPage();
  await page.goto(`${baseURL}/admin/surveys`);
  await expect(page.locator(".surveys-list li")).toHaveCount(2);
  await expect(
    page.getByText("Standard für Teilantworten", { exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("link", { name: "Shared design fixture", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Fragebogen bearbeiten" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Veröffentlichen", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", {
      name: "In Papierkorb verschieben",
      exact: true,
    }),
  ).toHaveCount(0);
  expect(
    await page.evaluate(
      async (sid) =>
        (
          await fetch(`/api/v1/surveys/${sid}/publish`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              operationId: "browser-denied",
              expectedRevision: 1,
            }),
          })
        ).status,
      process.env.SURVEY_SHARED_ID,
    ),
  ).toBe(404);
  await page.screenshot({
    path: `${proof}/surveys-module-designer.png`,
    fullPage: true,
  });
  await page.goto(`${baseURL}/admin/surveys/${process.env.SURVEY_PRIVATE_ID}`);
  await expect(page.getByRole("alert")).toContainText("Umfrage nicht gefunden");
  await expect(
    page.getByRole("region", { name: "Fragebogen bearbeiten" }),
  ).toHaveCount(0);
  await context.close();
});
