import { expect, test } from "@playwright/test";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const session = process.env.KLARA_SESSION;

if (!baseUrl || !artifactDirectory || !session) {
  throw new Error(
    "LEONAID_E2E_BASE_URL, LEONAID_E2E_ARTIFACT_DIR und KLARA_SESSION sind erforderlich",
  );
}

test("Charity-Admin legt eine neutrale Aktion vollständig über die Oberfläche an", async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1200 },
    ignoreHTTPSErrors: true,
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: session,
      url: baseUrl,
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
    },
  ]);
  const page = await context.newPage();
  try {
    await page.goto(`${baseUrl}/admin/actions/new`);
    await expect(
      page.getByRole("heading", { name: "Neue Aktion anlegen" }),
    ).toBeVisible();

    await page.getByTestId("action-name").fill("Quartalsaktion Browser 2027");
    await page
      .getByTestId("action-carrier")
      .fill("Lions Hilfswerk Beispielstadt");
    await page.getByTestId("action-slug").fill("quartalsaktion-browser-2027");
    await page
      .getByTestId("action-purpose")
      .fill("Förderung lokaler Bildungs- und Freizeitangebote.");
    await page.getByTestId("action-start").fill("2027-04-01");
    await page.getByTestId("action-end").fill("2027-06-30");
    await page.locator('input[value="acquisition"]').check();
    await page.locator('input[value="offerings"]').check();
    await page.locator('input[value="ordering"]').check();
    await page.locator('input[value="invoicing"]').check();
    await page.getByTestId("action-goal").fill("20000");
    await page.getByTestId("action-unit").fill("EUR");
    await page.getByTestId("action-actual").fill("0");
    await page.getByTestId("action-currency").fill("EUR");
    await page
      .getByTestId("beneficiary-name-0")
      .fill("Bildungsinsel Beispielstadt");
    await page
      .getByTestId("beneficiary-description-0")
      .fill("Schafft kostenfreie Lernangebote.");
    await page.getByTestId("add-beneficiary").click();
    await page
      .getByTestId("beneficiary-name-1")
      .fill("Freizeithafen Musterbogen");
    await page
      .getByTestId("beneficiary-description-1")
      .fill("Ermöglicht inklusive Ferienprogramme.");
    await page.getByTestId("action-submit").click();

    const status = page.locator("#action-status");
    await expect(status).toHaveAttribute("data-state", "success");
    await expect(status).toContainText(
      "Quartalsaktion Browser 2027 wurde als Entwurf angelegt.",
    );
    const actionId = await status.getAttribute("data-action-id");
    expect(actionId).toMatch(/^[0-9a-f-]{36}$/);

    const detail = await page.evaluate(async (id) => {
      const response = await fetch(`/api/v1/actions/${id}`, {
        credentials: "include",
        headers: { Accept: "application/json" },
      });
      return { body: await response.json(), status: response.status };
    }, actionId);
    expect(detail.status).toBe(200);
    expect(detail.body).toMatchObject({
      name: "Quartalsaktion Browser 2027",
      status: "draft",
      capabilities: ["acquisition", "invoicing", "offerings", "ordering"],
      goal: {
        goalValue: "20000",
        actualValue: "0",
        unit: "EUR",
        currency: "EUR",
      },
    });
    expect(detail.body.beneficiaries).toHaveLength(2);

    await page.screenshot({
      path: `${artifactDirectory}/action-created.png`,
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});
