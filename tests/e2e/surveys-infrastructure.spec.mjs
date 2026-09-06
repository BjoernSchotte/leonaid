import { expect, test } from "@playwright/test";
const baseURL = process.env.LEONAID_E2E_BASE_URL;
const token = process.env.SURVEY_ADMIN_SESSION;
if (!baseURL || !token) throw new Error("Survey fixture access is required");
test("survey infrastructure reaches member and public hosts with real identity", async ({
  browser,
}) => {
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
  await page.goto(`${baseURL}/admin/`);
  await expect(
    page.getByText("Survey Test Admin", { exact: true }).first(),
  ).toBeVisible();
  const identity = await page.evaluate(async () => {
    const response = await fetch("/api/v1/identity/me");
    return { status: response.status, body: await response.json() };
  });
  expect(identity.status).toBe(200);
  expect(JSON.stringify(identity.body)).toContain("Survey Test Admin");
  const publicResponse = await page.goto(`${baseURL}/`);
  expect(publicResponse.status()).toBe(200);
  await expect(page.locator("body")).toContainText("Lions");
  await page.screenshot({
    path: `${process.env.LEONAID_E2E_ARTIFACT_DIR}/surveys-public.png`,
    fullPage: true,
  });
  await context.close();
});
