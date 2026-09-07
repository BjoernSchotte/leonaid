import { test, expect } from "@playwright/test";
const baseURL = process.env.LEONAID_E2E_BASE_URL;
const surveyId = process.env.SURVEY_KRAPFENTAXI_ID;
if (!baseURL || !surveyId) throw new Error("Published survey fixture required");
async function rate(page, name, value) {
  const question = page.locator(`[data-name=${name}]`);
  await expect(question).toBeVisible();
  // SurveyJS can replace the radio view with its mobile dropdown after resize
  // observation. Retry only the same value selection, never the whole journey.
  await expect(async () => {
    const dropdown = question.getByRole("combobox");
    if (await dropdown.isVisible()) {
      await dropdown.click({ timeout: 1000 });
      await page
        .getByRole("option", { name: String(value), exact: true })
        .click({ timeout: 1000 });
    } else {
      await question
        .locator(`input[type=radio][value="${value}"]`)
        .press("Space", { timeout: 1000 });
    }
  }).toPass({ timeout: 15000, intervals: [100, 250] });
}
for (const width of [1440, 390, 320]) {
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
      await rate(page, "delivery_rating", 5);
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
      const rating = page.locator("[data-name=delivery_rating]");
      // Hydration and ResizeObserver can switch the restored rating's view.
      // Re-read the active view while checking the same persisted value.
      await expect(async () => {
        const dropdown = rating.getByRole("combobox");
        if (await dropdown.isVisible())
          await expect(dropdown).toContainText("5", { timeout: 1000 });
        else
          await expect(
            rating.locator('input[type=radio][value="5"]'),
          ).toBeChecked({ timeout: 1000 });
      }).toPass({ timeout: 15000, intervals: [100, 250] });
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
      async function progressFits() {
        const buttons = page.locator(
          ".survey-runner .sd-progress-buttons__button",
        );
        await expect(buttons).toHaveCount(3);
        expect(
          await buttons.evaluateAll((elements) =>
            elements.every((element) => {
              const box = element.getBoundingClientRect();
              const container = element
                .closest(".sd-progress-buttons__list-container")
                .getBoundingClientRect();
              return (
                box.left >= container.left - 1 &&
                box.right <= container.right + 1 &&
                box.left >= 0 &&
                box.right <= innerWidth
              );
            }),
          ),
        ).toBe(true);
      }
      await progressFits();
      await page.screenshot({
        path: `${process.env.LEONAID_E2E_ARTIFACT_DIR}/surveys-branding-progress-${width}.png`,
        fullPage: true,
      });
      await page.getByRole("button", { name: "Weiter", exact: true }).click();
      await page
        .locator("[data-name=freshness]")
        .getByRole("radio")
        .first()
        .press("Space");
      await progressFits();
      await page.getByRole("button", { name: "Weiter", exact: true }).click();
      await rate(page, "nps", 10);
      await progressFits();
      await page.getByRole("button", { name: "Zurück", exact: true }).click();
      await expect(
        page.locator("[data-name=freshness]").getByRole("radio").first(),
      ).toBeChecked();
      await progressFits();
      await page.getByRole("button", { name: "Weiter", exact: true }).click();
      await page
        .getByRole("button", { name: "Abschließen", exact: true })
        .click();
      await expect(
        page.getByRole("heading", {
          name: "Vielen Dank für Ihre Rückmeldung.",
        }),
      ).toBeVisible();
      const completed = await page.evaluate(
        async (path) => (await fetch(path)).json(),
        endpoint,
      );
      await expect(page.locator(".survey-completion-message")).toHaveText(
        "Ihre Antworten sind eingegangen.",
      );
      expect(completed.response.status).toBe("completed");
      expect(completed.response.answers).toEqual({
        delivery_rating: 5,
        freshness: "fresh",
        nps: 10,
      });
      await page.screenshot({
        path: `${process.env.LEONAID_E2E_ARTIFACT_DIR}/surveys-branding-${width}.png`,
        fullPage: true,
      });
    } finally {
      await context.close();
    }
  });
}
