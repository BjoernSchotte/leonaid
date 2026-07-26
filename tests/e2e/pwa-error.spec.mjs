import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const annaSession = process.env.ANNA_SESSION;

if (!baseUrl || !artifactDirectory || !annaSession) {
  throw new Error(
    "LEONAID_E2E_BASE_URL, LEONAID_E2E_ARTIFACT_DIR und ANNA_SESSION sind erforderlich",
  );
}

test.use({
  ignoreHTTPSErrors: true,
  viewport: { width: 390, height: 844 },
});

test("POC-062 erklärt einen realen Twenty-Ausfall", async ({
  context,
  page,
}) => {
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
  await page.goto(`${baseUrl}/app/sponsors`);
  await expect(page.locator('[data-testid="display-name"]')).toHaveText(
    "Anna Akquise",
  );
  await expect(page.getByText("Sponsorenliste nicht erreichbar")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Sponsoren neu laden" }),
  ).toBeVisible();
  const results = await new AxeBuilder({ page }).analyze();
  expect(
    results.violations.filter(({ impact }) =>
      ["critical", "serious"].includes(impact),
    ),
  ).toEqual([]);
  await page.screenshot({
    path: `${artifactDirectory}/pwa-error-chromium-390.png`,
    fullPage: true,
  });
});
