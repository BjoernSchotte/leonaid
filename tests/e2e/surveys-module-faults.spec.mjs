import { test, expect } from "./csp-guard.mjs";
const baseURL = process.env.LEONAID_E2E_BASE_URL;
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

test("a settings save keeps unsaved input in the other settings forms", async ({
  browser,
}) => {
  const context = await session(browser, process.env.SURVEY_ADMIN_SESSION);
  const page = await context.newPage();
  await page.goto(`${baseURL}/admin/surveys/new`);
  await page
    .getByLabel("Titel der Umfrage", { exact: true })
    .fill("Einstellungen während des Speicherns");
  await page
    .getByRole("button", { name: "Umfrage erstellen", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Fragebogen bearbeiten" }),
  ).toBeVisible();
  const id = page.url().split("/").at(-1);
  // Hold the survey reload that follows the scheduled-end save until the
  // other forms have been edited. That reload is where refresh() used to
  // reset every settings field to the server value.
  let arm = false;
  let held;
  const reached = new Promise((resolve) => {
    held = resolve;
  });
  let release;
  const released = new Promise((resolve) => {
    release = resolve;
  });
  const surveyRecord = (url) => url.pathname === `/api/v1/surveys/${id}`;
  await page.route(surveyRecord, async (route) => {
    if (arm && route.request().method() === "GET") {
      arm = false;
      held();
      await released;
    }
    await route.continue();
  });
  await page.getByText("Zugang zur Umfrage", { exact: true }).click();
  await page.getByText("Geplantes Ende", { exact: true }).click();
  await page
    .getByText("Teilantworten nach Inaktivität", { exact: true })
    .click();
  const timeout = page.getByLabel("Abweichender Zeitraum in Sekunden");
  const access = page.getByRole("combobox", {
    name: "Zugangsmodus",
    exact: true,
  });
  await expect(timeout).toHaveValue("");
  await expect(access).toHaveValue("anonymous");
  const future = new Date(Date.now() + 2 * 86400000).toISOString().slice(0, 16);
  await page.getByLabel("Teilnahme endet am", { exact: true }).fill(future);
  arm = true;
  await page
    .getByRole("button", { name: "Geplantes Ende speichern", exact: true })
    .click();
  await reached;
  await timeout.fill("7");
  await access.selectOption("invitation");
  release();
  await expect(
    page.getByText("Geplantes Ende wurde gespeichert.", { exact: true }),
  ).toBeVisible();
  await expect(timeout).toHaveValue("7");
  await expect(access).toHaveValue("invitation");
  await expect(
    page.getByLabel("Teilnahme endet am", { exact: true }),
  ).toHaveValue(future);
  await page
    .getByRole("button", { name: "Zeitraum speichern", exact: true })
    .click();
  await expect(
    page.getByText("Zeitraum wurde gespeichert.", { exact: true }),
  ).toBeVisible();
  // The access mode was never saved, so the timeout refresh keeps it too.
  await expect(access).toHaveValue("invitation");
  const stored = await page.evaluate(
    async (key) => (await fetch(`/api/v1/surveys/${key}`)).json(),
    id,
  );
  expect(stored.inactivityTimeoutSeconds).toBe(7);
  expect(stored.accessMode).toBe("anonymous");
  expect(new Date(stored.endsAt).toISOString().slice(0, 16)).toBe(future);
  await page.unroute(surveyRecord);
  await page.reload();
  await page.getByText("Zugang zur Umfrage", { exact: true }).click();
  await page
    .getByText("Teilantworten nach Inaktivität", { exact: true })
    .click();
  await expect(timeout).toHaveValue("7");
  await expect(access).toHaveValue("anonymous");
  await context.close();
});
