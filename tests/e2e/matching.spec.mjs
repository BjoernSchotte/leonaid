import { expect, test } from "@playwright/test";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const annaSession = process.env.ANNA_SESSION;

if (!baseUrl || !artifactDirectory || !annaSession) {
  throw new Error(
    "LEONAID_E2E_BASE_URL, LEONAID_E2E_ARTIFACT_DIR und ANNA_SESSION sind erforderlich",
  );
}

test("Akquisiteurin sieht Zuständigkeit und bestätigt Mehrfachzuordnung", async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    ignoreHTTPSErrors: true,
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: annaSession,
      url: baseUrl,
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
    },
  ]);
  const page = await context.newPage();
  try {
    await page.goto(`${baseUrl}/app/sponsors`);
    await expect(page.locator('[data-testid="display-name"]')).toHaveText(
      "Anna Akquise",
    );
    await expect(
      page.getByRole("heading", { name: "Sponsor erfassen" }),
    ).toBeVisible();

    await page
      .locator('[data-testid="sponsor-company"]')
      .fill("Baeckerei  Sonnenseite K.G.");
    await page.locator("#sponsor-postal-code").fill("99999");
    await page.locator("#sponsor-city").fill("Nicht überschreiben");
    await page.locator('[data-testid="sponsor-preview"]').click();

    await expect(
      page.getByRole("heading", { name: "Ein eindeutiger Treffer" }),
    ).toBeVisible();
    await expect(page.locator(".candidate")).toContainText(
      "Bäckerei Sonnenseite KG",
    );
    await expect(page.locator(".candidate")).toContainText("10243");
    await expect(page.locator(".assignment-warning")).toContainText(
      "Bernd Binder",
    );
    const confirmation = page.locator('[data-testid="sponsor-resolve"]');
    await expect(confirmation).toHaveText("Trotzdem ebenfalls zuordnen");
    await expect(page.locator('[data-testid="sponsor-success"]')).toHaveCount(
      0,
    );

    await page.screenshot({
      path: `${artifactDirectory}/matching-warning-mobile.png`,
      fullPage: true,
    });

    const resolutionResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/acquisition/sponsor-match/resolve") &&
        response.request().method() === "POST",
    );
    await confirmation.click();
    const resolved = await resolutionResponse;
    expect(resolved.status()).toBe(201);
    const payload = await resolved.json();
    expect(payload).toMatchObject({
      outcome: "reused",
      assignmentCreated: true,
      displayName: "Bäckerei Sonnenseite KG",
    });

    await expect(page.locator('[data-testid="sponsor-success"]')).toContainText(
      "Zuordnung gespeichert",
    );
    await expect(
      page.locator('[data-testid="shared-assignees"]'),
    ).toContainText("Anna Akquise");
    await expect(
      page.locator('[data-testid="shared-assignees"]'),
    ).toContainText("Bernd Binder");
    await expect(page.locator("#sponsor-status")).toContainText(
      "ist jetzt dir zugeordnet",
    );
    await page.screenshot({
      path: `${artifactDirectory}/matching-success-mobile.png`,
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});
