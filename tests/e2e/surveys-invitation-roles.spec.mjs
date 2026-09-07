import { test, expect } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
const base = process.env.LEONAID_E2E_BASE_URL;
const proof = process.env.LEONAID_E2E_ARTIFACT_DIR;

for (const mobile of [false, true])
  test(`invitation controls and recipient data are scoped on ${mobile ? "mobile" : "desktop"}`, async ({
    browser,
  }) => {
    test.setTimeout(120000);
    const fixture = JSON.parse(
      readFileSync(`${proof}/invitation-roles-private.json`, "utf8"),
    );
    const personas = JSON.parse(
      readFileSync(`${proof}/permission-browser-private.json`, "utf8"),
    ).actors;
    let pairs = 0;
    for (const [name, actor] of Object.entries(personas)) {
      const context = await browser.newContext({
        ignoreHTTPSErrors: true,
        viewport: mobile
          ? { width: 390, height: 844 }
          : { width: 1440, height: 1000 },
      });
      await context.addCookies([
        {
          name: "__Host-leonaid_session",
          value: actor.token,
          url: base,
          secure: true,
          httpOnly: true,
          sameSite: "Lax",
        },
      ]);
      try {
        const page = await context.newPage();
        for (const survey of fixture.scopes) {
          const allowed =
            ["admin", "owner", "manage_invitations"].includes(name) ||
            (name === "manager" && survey.kind === "member-action");
          const canOpen =
            !["member", "outsider"].includes(name) &&
            (name !== "manager" || survey.kind === "member-action");
          await page.goto(`${base}/admin/surveys/${survey.id}`);
          if (canOpen)
            await expect(page.locator("[data-survey-status]")).toHaveAttribute(
              "data-survey-status",
              "active",
            );
          else
            await expect(page.getByRole("alert")).toContainText(
              "Umfrage nicht gefunden",
            );
          const panel = page.getByText("Einladungen (1)", { exact: true });
          await expect(panel).toHaveCount(allowed ? 1 : 0);
          if (allowed) {
            await panel.click();
            await expect(
              page.getByText("matrix-recipient@example.com", { exact: true }),
            ).toBeVisible();
            await expect(
              page.getByRole("button", {
                name: "Einladung senden",
                exact: true,
              }),
            ).toBeVisible();
          } else {
            await expect(
              page.getByText("matrix-recipient@example.com", { exact: true }),
            ).toHaveCount(0);
            await expect(
              page.getByRole("button", {
                name: "Einladung senden",
                exact: true,
              }),
            ).toHaveCount(0);
          }
          const response = await context.request.get(
            `${base}/api/v1/surveys/${survey.id}/invitations`,
          );
          expect(response.status()).toBe(allowed ? 200 : 404);
          pairs += 1;
        }
      } finally {
        await context.close();
      }
    }
    expect(pairs).toBe(28);
    writeFileSync(
      `${proof}/invitation-controls-${mobile}.json`,
      JSON.stringify({ mobile, pairs, recipientDataScoped: true }),
    );
  });

for (const kind of ["standalone", "action"])
  for (const mobile of [false, true])
    test(`invitation-only member manages ${kind} invitations on ${mobile ? "mobile" : "desktop"}`, async ({
      browser,
      request,
    }) => {
      const fixture = JSON.parse(
        readFileSync(`${proof}/invitation-roles-private.json`, "utf8"),
      );
      const survey = fixture.journeys.find(
        (row) => row.kind === kind && row.mobile === mobile,
      );
      const options = {
        ignoreHTTPSErrors: true,
        viewport: mobile
          ? { width: 390, height: 844 }
          : { width: 1440, height: 1000 },
      };
      const member = await browser.newContext(options);
      const recipient = await browser.newContext(options);
      await member.addCookies([
        {
          name: "__Host-leonaid_session",
          value: fixture.token,
          url: base,
          secure: true,
          httpOnly: true,
          sameSite: "Lax",
        },
      ]);
      const api = `${base}/api/v1/surveys/${survey.id}`;
      const button = (page, name) =>
        page.getByRole("button", { name, exact: true });
      try {
        const page = await member.newPage();
        await page.goto(`${base}/admin/surveys/${survey.id}`);
        await expect(page.locator("[data-survey-status]")).toHaveAttribute(
          "data-survey-status",
          "active",
        );
        await expect(
          page.getByRole("region", {
            name: "Fragebogen bearbeiten",
            exact: true,
          }),
        ).toHaveCount(0);
        for (const name of [
          "Veröffentlichen",
          "Teilnahme beenden",
          "In Papierkorb verschieben",
        ])
          await expect(button(page, name)).toHaveCount(0);
        expect((await member.request.get(api + "/draft")).status()).toBe(404);
        expect(
          (
            await member.request.get(api + "/response-selections/versions")
          ).status(),
        ).toBe(404);
        await page.getByText("Einladungen (0)", { exact: true }).click();
        const email = `role-${survey.id}@example.com`;
        await page
          .getByLabel("E-Mail des Empfängers", { exact: true })
          .fill(email);
        await button(page, "Einladung senden").click();
        await expect(
          page.getByText("Einladung wurde zum Versand vorgemerkt.", {
            exact: true,
          }),
        ).toBeVisible();
        await expect
          .poll(
            async () => {
              const result = await (
                await request.get("http://mailpit:8025/mail/api/v1/messages")
              ).json();
              return result.messages.filter((message) =>
                message.To.some((to) => to.Address === email),
              ).length;
            },
            { timeout: 15000 },
          )
          .toBe(1);
        await button(page, "Versandstatus aktualisieren").click();
        await expect(
          page.getByText("Versendet", { exact: true }),
        ).toBeVisible();
        const messages = await (
          await request.get("http://mailpit:8025/mail/api/v1/messages")
        ).json();
        const mail = messages.messages.find((message) =>
          message.To.some((to) => to.Address === email),
        );
        const body = await (
          await request.get(
            `http://mailpit:8025/mail/api/v1/message/${mail.ID}`,
          )
        ).json();
        const link = new URL(
          body.Text.match(/https:\/\/[^\s]+#invitation=[A-Za-z0-9_-]+/)[0],
        );
        const invitationUrl = `${base}${link.pathname}${link.hash}`;
        const respondent = await recipient.newPage();
        await respondent.goto(invitationUrl);
        await button(respondent, "Umfrage beginnen").click();
        await respondent
          .locator('[data-name="answer"] input[type="text"]')
          .fill("Invitation-only journey response");
        await expect(respondent.locator("[data-save-state]")).toHaveAttribute(
          "data-save-state",
          "saved",
        );
        await button(respondent, "Abschließen").click();
        await expect(
          respondent.getByRole("heading", {
            name: "Vielen Dank für Ihre Rückmeldung.",
            exact: true,
          }),
        ).toBeVisible();
        await button(page, "Einladung widerrufen").click();
        await expect(
          page.getByText("Einladung wurde widerrufen.", { exact: true }),
        ).toBeVisible();
        await respondent.reload();
        await expect(respondent.getByRole("status")).toContainText(
          "Teilnahme nicht gefunden",
        );
        await respondent.goto(invitationUrl);
        await button(respondent, "Umfrage beginnen").click();
        await expect(respondent.getByRole("status")).toContainText(
          "nicht mehr gültig",
        );
        writeFileSync(
          `${proof}/invitation-role-${kind}-${mobile}.json`,
          JSON.stringify({
            kind,
            mobile,
            singleGrantJourney: true,
            delivered: true,
            completed: true,
            revoked: true,
          }),
        );
      } finally {
        await member.close();
        await recipient.close();
      }
    });
