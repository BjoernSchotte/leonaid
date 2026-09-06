import { test, expect } from "@playwright/test";
import { writeFileSync } from "node:fs";
const base = process.env.LEONAID_E2E_BASE_URL;
const proof = process.env.LEONAID_E2E_ARTIFACT_DIR;

test("member invites through Mailpit, recipient completes, and revocation blocks link and resume", async ({
  browser,
  request,
}) => {
  const admin = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1440, height: 1000 },
  });
  const recipient = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 390, height: 844 },
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
      .fill("Einladung zum Lions-Feedback");
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
    const email = `browser-survey-${id}@example.com`;
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
      if (attempts.length === 1) await route.abort("failed");
      else if (attempts.length === 2)
        await route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({
            error: {
              code: "internal_error",
              message: "Synthetic unconfirmed server response",
              requestId: "synthetic",
            },
          }),
        });
      else await route.fulfill({ response });
    });
    await page
      .getByRole("button", { name: "Einladung senden", exact: true })
      .click();
    await expect(page.getByRole("alert")).toBeVisible();
    await page
      .getByRole("button", { name: "Einladung senden", exact: true })
      .click();
    await expect(page.getByRole("alert")).toContainText(
      "Synthetic unconfirmed server response",
    );
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
    const messages = await (
      await request.get("http://mailpit:8025/mail/api/v1/messages")
    ).json();
    const mail = messages.messages.find((m) =>
      m.To.some((to) => to.Address === email),
    );
    const body = await (
      await request.get(`http://mailpit:8025/mail/api/v1/message/${mail.ID}`)
    ).json();
    const link = body.Text.match(
      /https:\/\/[^\s]+#invitation=[A-Za-z0-9_-]+/,
    )[0];
    const url = new URL(link);
    // Same deployment path/fragment; the isolated Docker browser uses its internal proxy origin.
    const invitationUrl = `${base}${url.pathname}${url.hash}`;
    const respondent = await recipient.newPage();
    const requestUrls = [];
    respondent.on("request", (r) => requestUrls.push(r.url()));
    await respondent.goto(invitationUrl);
    await expect(respondent.getByRole("status")).toContainText(
      "zugeordnet werden",
    );
    await respondent
      .getByRole("button", { name: "Umfrage beginnen", exact: true })
      .click();
    const field = respondent.locator(
      "[data-name=question_first] input[type=text]",
    );
    await field.fill("Personal invitation works");
    await expect(respondent.locator("[data-save-state]")).toHaveAttribute(
      "data-save-state",
      "saved",
    );
    expect(new URL(respondent.url()).hash).toBe("");
    const pid = new URL(respondent.url()).searchParams.get("participation");
    expect(pid).toBeTruthy();
    const cookie = (await recipient.cookies()).find(
      (c) => c.name === `__Host-survey_${pid}`,
    );
    expect(cookie.httpOnly && cookie.secure).toBe(true);
    const secret = new URLSearchParams(url.hash.slice(1)).get("invitation");
    expect(requestUrls.some((value) => value.includes(secret))).toBe(false);
    await respondent
      .getByRole("button", { name: "Abschließen", exact: true })
      .click();
    await expect(
      respondent.getByRole("heading", {
        name: "Vielen Dank für Ihre Rückmeldung.",
      }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Einladung widerrufen", exact: true })
      .click();
    await expect(
      page.getByText("Einladung wurde widerrufen.", { exact: true }),
    ).toBeVisible();
    await respondent.reload();
    await expect(respondent.getByRole("status")).toContainText(
      "Teilnahme nicht gefunden",
    );
    await respondent.goto(invitationUrl);
    await respondent
      .getByRole("button", { name: "Umfrage beginnen", exact: true })
      .click();
    await expect(respondent.getByRole("status")).toContainText(
      "nicht mehr gültig",
    );
    writeFileSync(
      `${proof}/survey-invitation-browser.json`,
      JSON.stringify({ survey: id, email }),
    );
  } finally {
    await recipient.close();
    await admin.close();
  }
});
