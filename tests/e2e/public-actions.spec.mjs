import { expect, test } from "@playwright/test";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;

if (!baseUrl || !artifactDirectory) {
  throw new Error(
    "LEONAID_E2E_BASE_URL and LEONAID_E2E_ARTIFACT_DIR are required",
  );
}

test.use({ ignoreHTTPSErrors: true });

test("öffentlicher Alias wechselt den Jahrgang, Archive bleiben unverändert", async ({
  page,
}) => {
  await page.goto(`${baseUrl}/krapfentaxi`);
  await expect(page).toHaveTitle(/Krapfentaxi 2027/);
  await expect(page.getByTestId("public-route-state")).toHaveText(
    "Aktuell veröffentlicht",
  );
  await expect(page.getByTestId("public-action-name")).toHaveText(
    "Krapfentaxi 2027",
  );
  await expect(page.getByTestId("public-canonical-path")).toHaveText(
    "/archive/krapfentaxi-2027",
  );
  await page.screenshot({
    path: `${artifactDirectory}/public-alias-2027.png`,
    fullPage: true,
  });

  await page.goto(`${baseUrl}/archive/krapfentaxi-2026`);
  await expect(page).toHaveURL(/\/archive\/krapfentaxi-2026$/);
  await expect(page.getByTestId("public-route-state")).toHaveText(
    "Dauerhaftes Archiv",
  );
  await expect(page.getByTestId("public-action-name")).toHaveText(
    "Krapfentaxi 2026",
  );
  await expect(page.getByTestId("public-canonical-path")).toHaveText(
    "/archive/krapfentaxi-2026",
  );
  await expect(page.getByTestId("public-order-form")).toBeVisible();
  await expect(page.getByTestId("public-order-submit")).toBeDisabled();
  await expect(page.locator('input[name="companyName"]')).toBeDisabled();
  await page.screenshot({
    path: `${artifactDirectory}/public-archive-2026.png`,
    fullPage: true,
  });

  await page.goto(`${baseUrl}/winterpause`);
  await expect(page.getByTestId("public-inactive")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Derzeit keine aktive Aktion" }),
  ).toBeVisible();
  await expect(page.locator("form")).toHaveCount(0);
  await page.screenshot({
    path: `${artifactDirectory}/public-inactive.png`,
    fullPage: true,
  });
});
