import { expect, test } from "@playwright/test";
const baseURL = process.env.LEONAID_E2E_BASE_URL;
const token =
  process.env.SURVEY_MEMBER_SESSION ?? process.env.SURVEY_ADMIN_SESSION;
const identityName = process.env.SURVEY_MEMBER_SESSION
  ? "Survey Test Member"
  : "Survey Test Admin";
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
  try {
    await test.step("member-host", async () => {
      await page.goto(`${baseURL}/admin/`);
      await expect(
        page.getByText(identityName, { exact: true }).first(),
      ).toBeVisible();
      const identity = await page.evaluate(async () => {
        const response = await fetch("/api/v1/identity/me");
        return { status: response.status, body: await response.json() };
      });
      expect(identity.status).toBe(200);
      expect(JSON.stringify(identity.body)).toContain(identityName);
    });
    await test.step("public-host", async () => {
      const publicResponse = await page.goto(`${baseURL}/`);
      expect(publicResponse.status()).toBe(200);
      await expect(page.locator("body")).toContainText("Lions");
    });
    if (process.env.SURVEY_KRAPFENTAXI_ID) {
      await test.step("public-survey-shell", async () => {
        const response = await page.goto(
          `${baseURL}/surveys/${process.env.SURVEY_KRAPFENTAXI_ID}`,
        );
        expect(response.status()).toBe(200);
        await expect(
          page.getByRole("button", { name: "Umfrage beginnen" }),
        ).toBeVisible();
        await expect(page.locator("body")).toContainText(
          "Wie war Ihr Krapfentaxi?",
        );
      });
    }
    await page.screenshot({
      path: `${process.env.LEONAID_E2E_ARTIFACT_DIR}/surveys-public.png`,
      fullPage: true,
    });
    if (process.env.SURVEY_FOUNDATION_FORCE_FAILURE === "1") {
      expect(`SURVEY_FOUNDATION_SECRET_CANARY:${token}`).toBe(
        "deliberate failure",
      );
    }
  } finally {
    await context.close();
  }
});
