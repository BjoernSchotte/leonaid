import { test, expect } from "@playwright/test";
const baseURL = process.env.LEONAID_E2E_BASE_URL;
const surveyId = process.env.SURVEY_KRAPFENTAXI_ID;
if (!baseURL || !surveyId) throw new Error("Published survey fixture required");
for (const width of [1440, 390]) {
  test(`host logo loads with saved participation at width ${width}`, async ({
    browser,
  }) => {
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width, height: 900 },
    });
    try {
      const page = await context.newPage();
      await page.goto(`${baseURL}/surveys/${surveyId}`);
      await page.getByRole("button", { name: "Umfrage beginnen" }).click();
      const logo = page
        .locator(".survey-runner")
        .getByRole("img", { name: "LeonAid", exact: true });
      await expect(logo).toBeVisible();
      await expect(logo).toHaveAttribute("src", "/favicon.svg");
      await expect
        .poll(() => logo.evaluate((img) => img.naturalWidth))
        .toBeGreaterThan(0);
      await page
        .locator("[data-name=delivery_rating]")
        .getByRole("radio")
        .nth(4)
        .press("Space");
      await expect(page.locator("[data-save-state]")).toHaveAttribute(
        "data-save-state",
        "saved",
      );
      const pid = new URL(page.url()).searchParams.get("participation");
      expect(pid).toBeTruthy();
      const endpoint = `/api/v1/public/surveys/${surveyId}/participations/${pid}`;
      const stored = await page.evaluate(
        async (path) => (await fetch(path)).json(),
        endpoint,
      );
      expect(stored.response.answers.delivery_rating).toBe(5);
      await page.reload();
      await expect(logo).toBeVisible();
      await expect(
        page.locator("[data-name=delivery_rating]").getByRole("radio").nth(4),
      ).toBeChecked();
      const restored = await page.evaluate(
        async (path) => (await fetch(path)).json(),
        endpoint,
      );
      expect(restored.response).toEqual(stored.response);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: `${process.env.LEONAID_E2E_ARTIFACT_DIR}/surveys-branding-${width}.png`,
        fullPage: true,
      });
    } finally {
      await context.close();
    }
  });
}
