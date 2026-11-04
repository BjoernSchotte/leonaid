import { test, expect } from "./csp-guard.mjs";
const base = process.env.LEONAID_E2E_BASE_URL;

test("invitation send retries two lost acknowledgements with one delivery", async ({
  browser,
  request,
}) => {
  const admin = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1440, height: 1000 },
  });
  await admin.addCookies([
    {
      name: "__Host-leonaid_session",
      value: process.env.SURVEY_ADMIN_SESSION,
      url: base,
      secure: true,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  try {
    const page = await admin.newPage();
    await page.goto(`${base}/admin/surveys/new`);
    await page
      .getByLabel("Titel der Umfrage", { exact: true })
      .fill("Einladung mit verlorener Bestätigung");
    await page
      .getByRole("button", { name: "Umfrage erstellen", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "Fragebogen bearbeiten" }),
    ).toBeVisible();
    const id = page.url().split("/").at(-1);
    await page.getByText("Zugang zur Umfrage", { exact: true }).click();
    await page
      .getByRole("combobox", { name: "Zugangsmodus", exact: true })
      .selectOption("invitation");
    await page
      .getByRole("button", { name: "Zugangsmodus speichern", exact: true })
      .click();
    await expect(
      page.getByText("Zugangsmodus wurde gespeichert.", { exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Veröffentlichen", exact: true })
      .click();
    await expect(page.locator("[data-survey-status]")).toHaveAttribute(
      "data-survey-status",
      "active",
    );
    await page.getByText("Einladungen (0)", { exact: true }).click();
    const email = `browser-survey-faults-${id}@example.com`;
    await page.getByLabel("E-Mail des Empfängers", { exact: true }).fill(email);
    await page
      .getByLabel("Name des Empfängers (optional)", { exact: true })
      .fill("Synthetic browser recipient");
    const attempts = [];
    await page.route(`**/api/v1/surveys/${id}/invitations`, async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      attempts.push(route.request().postDataJSON());
      const response = await route.fetch();
      expect(response.status()).toBe(200);
      // Lose two real acknowledgements after the server has committed each request.
      // A retry must reuse the original operation without duplicating delivery.
      if (attempts.length <= 2) await route.abort("failed");
      else await route.fulfill({ response });
    });
    await page
      .getByRole("button", { name: "Einladung senden", exact: true })
      .click();
    await expect(page.getByRole("alert")).toBeVisible();
    await page
      .getByRole("button", { name: "Einladung senden", exact: true })
      .click();
    await expect.poll(() => attempts.length).toBe(2);
    await expect(page.getByRole("alert")).toBeVisible();
    await page
      .getByRole("button", { name: "Einladung senden", exact: true })
      .click();
    await expect(
      page.getByText("Einladung wurde zum Versand vorgemerkt.", {
        exact: true,
      }),
    ).toBeVisible();
    expect(attempts).toHaveLength(3);
    expect(attempts[2]).toEqual(attempts[0]);
    expect(attempts[1]).toEqual(attempts[0]);
    await expect
      .poll(
        async () => {
          const messages = await (
            await request.get("http://mailpit:8025/mail/api/v1/messages")
          ).json();
          return messages.messages.filter((m) =>
            m.To.some((to) => to.Address === email),
          ).length;
        },
        { timeout: 15000 },
      )
      .toBe(1);
  } finally {
    await admin.close();
  }
});
