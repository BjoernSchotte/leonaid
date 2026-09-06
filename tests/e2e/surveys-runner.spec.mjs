import { test, expect } from "@playwright/test";
const baseURL = process.env.LEONAID_E2E_BASE_URL;
const surveyId = process.env.SURVEY_KRAPFENTAXI_ID;
if (!baseURL || !surveyId) throw new Error("Published survey fixture required");
const saved = (page) =>
  expect(page.locator("[data-save-state]")).toHaveAttribute(
    "data-save-state",
    "saved",
  );

test("acknowledged text survives closing mid-page and hidden follow-up is removed", async ({
  browser,
}) => {
  const viewport = process.env.SURVEY_MOBILE
    ? { width: 390, height: 844 }
    : { width: 1280, height: 960 };
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport,
  });
  let page = await context.newPage();
  await page.goto(`${baseURL}/surveys/${surveyId}`);
  await page.getByRole("button", { name: "Umfrage beginnen" }).click();
  await expect(page.locator("[data-name=delivery_rating]")).toBeVisible();
  expect(
    await page
      .locator(".sd-theme-root")
      .first()
      .evaluate((el) =>
        getComputedStyle(el)
          .getPropertyValue("--sjs2-color-project-brand-600")
          .trim(),
      ),
  ).toBe("#00338d");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page
    .locator("[data-name=delivery_rating]")
    .getByRole("radio")
    .first()
    .press("Space");
  const comment = page.locator("[data-name=delivery_feedback] textarea");
  await comment.fill("Bitte nächste Lieferung etwas früher – danke!");
  await saved(page);
  await expect(comment).toBeFocused();
  const url = page.url();
  const participationId = new URL(url).searchParams.get("participation");
  expect(participationId).toBeTruthy();
  const cookieState = await context.storageState();
  await page.screenshot({
    path: `${process.env.LEONAID_E2E_ARTIFACT_DIR}/surveys-mid-page.png`,
    fullPage: true,
  });
  await context.close();
  await new Promise((resolve) => setTimeout(resolve, 2200));
  const resumed = await browser.newContext({
    ignoreHTTPSErrors: true,
    storageState: cookieState,
    viewport,
  });
  page = await resumed.newPage();
  let writes = 0;
  page.on("request", (request) => {
    if (
      request.method() === "PUT" &&
      request.url().includes("/participations/")
    )
      writes++;
  });
  await page.goto(url);
  await expect(
    page.locator("[data-name=delivery_feedback] textarea"),
  ).toHaveValue("Bitte nächste Lieferung etwas früher – danke!");
  await saved(page);
  await page.waitForTimeout(650);
  expect(writes).toBe(0);
  const read = () =>
    page.evaluate(
      async ({ surveyId, participationId }) => {
        const response = await fetch(
          `/api/v1/public/surveys/${surveyId}/participations/${participationId}`,
        );
        return response.json();
      },
      { surveyId, participationId },
    );
  expect((await read()).response.status).toBe("partial");
  await page
    .locator("[data-name=delivery_rating]")
    .getByRole("radio")
    .last()
    .press("Space");
  await saved(page);
  await expect(page.locator("[data-name=delivery_feedback]")).toHaveCount(0);
  expect((await read()).response.answers).not.toHaveProperty(
    "delivery_feedback",
  );
  await page.getByRole("button", { name: "Weiter", exact: true }).click();
  await page
    .locator("[data-name=freshness]")
    .getByRole("radio")
    .first()
    .press("Space");
  await page.locator("[data-name=notes] textarea").fill("Notiz auf Seite zwei");
  await saved(page);
  await page.reload();
  await expect(page.locator("[data-name=notes] textarea")).toHaveValue(
    "Notiz auf Seite zwei",
  );
  expect((await read()).response.currentPage).toBe("experience");
  await page.getByRole("button", { name: "Zurück", exact: true }).click();
  await expect(page.locator("[data-name=delivery_feedback]")).toHaveCount(0);
  await page.getByRole("button", { name: "Weiter", exact: true }).click();
  await expect(page.locator("[data-name=notes] textarea")).toHaveValue(
    "Notiz auf Seite zwei",
  );
  await page.getByRole("button", { name: "Weiter", exact: true }).click();
  await page
    .locator("[data-name=nps]")
    .getByRole("radio")
    .last()
    .press("Space");
  await saved(page);
  await page.getByRole("button", { name: "Abschließen", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Vielen Dank für Ihre Rückmeldung." }),
  ).toBeVisible();
  expect((await read()).response.status).toBe("completed");
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Vielen Dank für Ihre Rückmeldung." }),
  ).toBeVisible();
  await resumed.close();
});

test("offline edits stay pending and retry successfully after reconnect", async ({
  browser,
}) => {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 390, height: 844 },
  });
  const page = await context.newPage();
  await page.goto(`${baseURL}/surveys/${surveyId}`);
  await page.getByRole("button", { name: "Umfrage beginnen" }).click();
  await page
    .locator("[data-name=delivery_rating]")
    .locator("label")
    .first()
    .click();
  const field = page.locator("[data-name=delivery_feedback] textarea");
  await field.fill("Erste gespeicherte Fassung");
  await saved(page);
  await context.setOffline(true);
  await field.fill("Unterwegs ohne Netz ergänzt");
  await expect(page.locator("[data-save-state]")).toHaveAttribute(
    "data-save-state",
    "error",
  );
  await expect(field).toHaveValue("Unterwegs ohne Netz ergänzt");
  await context.setOffline(false);
  await saved(page);
  await page.reload();
  await expect(
    page.locator("[data-name=delivery_feedback] textarea"),
  ).toHaveValue("Unterwegs ohne Netz ergänzt");
  await context.close();
});
