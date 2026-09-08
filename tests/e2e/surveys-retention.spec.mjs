import { test, expect } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
const base = process.env.LEONAID_E2E_BASE_URL;
const proof = process.env.LEONAID_E2E_ARTIFACT_DIR;
async function contextFor(browser, token) {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 390, height: 844 },
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: token,
      url: base,
      secure: true,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  return context;
}
test("admin configures retention through the module and a member cannot", async ({
  browser,
}) => {
  const context = await contextFor(browser, process.env.SURVEY_ADMIN_SESSION);
  const page = await context.newPage();
  await page.goto(`${base}/admin/`);
  await page.getByRole("button", { name: "Navigation öffnen" }).click();
  await page
    .getByRole("navigation", { name: "Hauptnavigation" })
    .first()
    .getByRole("link", { name: "Umfragen", exact: true })
    .click();
  await page.getByText("Aufbewahrung und Papierkorb", { exact: true }).click();
  const ended = page.getByLabel("Tage nach Ende bis zum Papierkorb", {
    exact: true,
  });
  const trash = page.getByLabel(
    "Tage im Papierkorb bis zur endgültigen Löschung",
    { exact: true },
  );
  await expect(ended).toHaveValue("");
  await expect(trash).toHaveValue("");
  await ended.fill("30");
  await trash.fill("7");
  await page
    .getByRole("button", { name: "Aufbewahrungsfristen speichern" })
    .click();
  await expect(
    page.getByText("Aufbewahrungsfristen wurden gespeichert.", { exact: true }),
  ).toBeVisible();
  const saved = await context.request.get(`${base}/api/v1/survey-settings`);
  expect(saved.headers()["cache-control"]).toBe("no-store");
  expect(await saved.json()).toMatchObject({
    endedRetentionSeconds: 2592000,
    trashRetentionSeconds: 604800,
  });
  await page.reload();
  await page.getByText("Aufbewahrung und Papierkorb", { exact: true }).click();
  await expect(ended).toHaveValue("30");
  await expect(trash).toHaveValue("7");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: `${proof}/retention-mobile.png`,
    fullPage: true,
  });
  await ended.fill("");
  await trash.fill("");
  await page
    .getByRole("button", { name: "Aufbewahrungsfristen speichern" })
    .click();
  await expect(
    page.getByText("Aufbewahrungsfristen wurden gespeichert.", { exact: true }),
  ).toBeVisible();
  expect(
    await (await context.request.get(`${base}/api/v1/survey-settings`)).json(),
  ).toMatchObject({ endedRetentionSeconds: null, trashRetentionSeconds: null });
  await context.close();
  const member = JSON.parse(
    readFileSync(`${proof}/retention-member.json`, "utf8"),
  );
  const restricted = await contextFor(browser, member.token);
  const memberPage = await restricted.newPage();
  // Members without an operational web role use the surveys entry directly;
  // the general admin landing page correctly redirects them to the PWA.
  await memberPage.goto(`${base}/admin/surveys`);
  await expect(
    memberPage.getByRole("heading", { name: "Umfragen", exact: true }),
  ).toBeVisible();
  await expect(
    memberPage.getByText("Aufbewahrung und Papierkorb", { exact: true }),
  ).toHaveCount(0);
  expect(
    (await restricted.request.get(`${base}/api/v1/survey-settings`)).status(),
  ).toBe(403);
  await restricted.close();
  writeFileSync(
    `${proof}/retention-browser-proof.json`,
    JSON.stringify(
      {
        adminConfiguresAndReloads: true,
        daysStoredAsSeconds: true,
        emptyDisables: true,
        memberDenied: true,
        mobileOverflow: false,
      },
      null,
      2,
    ) + "\n",
  );
});
