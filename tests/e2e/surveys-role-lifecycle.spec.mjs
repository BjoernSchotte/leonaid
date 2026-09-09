import { test, expect } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
test.describe.configure({ mode: "parallel" });
const base = process.env.LEONAID_E2E_BASE_URL;
const proof = process.env.LEONAID_E2E_ARTIFACT_DIR;
for (const kind of ["standalone", "action"])
  for (const mobile of [false, true]) {
    test(`separate roles manage ${kind} lifecycle on ${mobile ? "mobile" : "desktop"}`, async ({
      browser,
    }) => {
      const fixture = JSON.parse(
        readFileSync(`${proof}/role-journeys-private.json`, "utf8"),
      );
      const survey = fixture.journeys.find(
        (row) => row.kind === kind && row.mobile === mobile,
      );
      const contexts = [];
      async function as(role) {
        const context = await browser.newContext({
          ignoreHTTPSErrors: true,
          viewport: mobile
            ? { width: 390, height: 844 }
            : { width: 1440, height: 1000 },
        });
        contexts.push(context);
        if (role)
          await context.addCookies([
            {
              name: "__Host-leonaid_session",
              value: fixture.actors[role].token,
              url: base,
              secure: true,
              httpOnly: true,
              sameSite: "Lax",
            },
          ]);
        const page = await context.newPage();
        await page.goto(`${base}/${role ? "admin/" : ""}surveys/${survey.id}`);
        return page;
      }
      const button = (page, name) =>
        page.getByRole("button", { name, exact: true });
      const state = (page, status) =>
        expect(page.locator("[data-survey-status]")).toHaveAttribute(
          "data-survey-status",
          status,
        );
      try {
        const design = await as("design");
        await design.locator('[data-question-id="answer"]').click();
        await design
          .getByLabel("Fragetitel", { exact: true })
          .fill("Separate role feedback");
        await button(design, "Jetzt speichern").click();
        await expect
          .poll(
            async () =>
              (
                await (
                  await design.request.get(
                    `${base}/api/v1/surveys/${survey.id}/draft`,
                  )
                ).json()
              ).definition.pages[0].elements[0].title,
          )
          .toBe("Separate role feedback");
        await expect(button(design, "Veröffentlichen")).toHaveCount(0);
        await design
          .getByText("Teilantworten nach Inaktivität", { exact: true })
          .click();
        await design
          .getByLabel("Abweichender Zeitraum in Sekunden", { exact: true })
          .fill("90");
        await button(design, "Zeitraum speichern").click();
        await expect(
          design.getByText("Zeitraum wurde gespeichert.", { exact: true }),
        ).toBeVisible();
        const publisher = await as("publish");
        await button(publisher, "Aktuellen Entwurf prüfen").click();
        await expect(
          publisher.getByText("Separate role feedback", { exact: true }),
        ).toBeVisible();
        await button(publisher, "Veröffentlichen").click();
        await state(publisher, "active");
        await expect(
          publisher.getByRole("region", {
            name: "Fragebogen bearbeiten",
            exact: true,
          }),
        ).toHaveCount(0);
        await expect(
          button(publisher, "In Papierkorb verschieben"),
        ).toHaveCount(0);
        const participant = await as(null);
        await button(participant, "Umfrage beginnen").click();
        await participant
          .locator('[data-name="answer"] input[type="text"]')
          .fill("Preserved role response");
        await expect(participant.locator("[data-save-state]")).toHaveAttribute(
          "data-save-state",
          "saved",
        );
        await button(participant, "Abschließen").click();
        await expect(
          participant.getByRole("heading", {
            name: "Vielen Dank für Ihre Rückmeldung.",
            exact: true,
          }),
        ).toBeVisible();
        await button(publisher, "Teilnahme beenden").click();
        await state(publisher, "ended");
        await expect(button(publisher, "Archivieren")).toHaveCount(0);
        const archivist = await as("archive");
        await button(archivist, "Archivieren").click();
        await state(archivist, "archived");
        await expect(
          button(archivist, "In Papierkorb verschieben"),
        ).toHaveCount(0);
        await button(archivist, "Aus Archiv holen").click();
        await state(archivist, "ended");
        const deleter = await as("delete");
        await expect(button(deleter, "Archivieren")).toHaveCount(0);
        await button(deleter, "In Papierkorb verschieben").click();
        await button(deleter, "Jetzt in Papierkorb verschieben").click();
        await state(deleter, "deleted");
        await button(deleter, "Wiederherstellen").click();
        await state(deleter, "ended");
        await deleter.reload();
        await state(deleter, "ended");
        const closed = await participant.request.get(
          `${base}/api/v1/public/surveys/${survey.id}`,
        );
        expect(closed.status()).toBe(409);
        if (mobile) {
          const deletionRequests = [];
          deleter.on("request", (request) => {
            if (
              request.method() === "POST" &&
              request.url().endsWith("/delete-permanently")
            )
              deletionRequests.push(request.postDataJSON());
          });
          await button(deleter, "In Papierkorb verschieben").click();
          await button(deleter, "Jetzt in Papierkorb verschieben").click();
          await state(deleter, "deleted");
          await button(deleter, "Endgültig löschen").click();
          await expect(
            button(deleter, "Löschung jetzt beauftragen"),
          ).toBeDisabled();
          await deleter
            .getByRole("checkbox", {
              name: "Ich möchte diese Umfrage mit allen zugehörigen Daten endgültig löschen.",
              exact: true,
            })
            .check();
          await button(deleter, "Löschung jetzt beauftragen").click();
          await expect(
            deleter
              .getByRole("region", { name: "Endgültige Löschung", exact: true })
              .getByRole("status"),
          ).toContainText("wurde endgültig gelöscht", { timeout: 30000 });
          expect(deletionRequests.length).toBeGreaterThan(0);
          writeFileSync(
            `${proof}/role-deletion-${kind}-private.json`,
            JSON.stringify(deletionRequests[0]),
          );
        }
        writeFileSync(
          `${proof}/role-lifecycle-${kind}-${mobile}.json`,
          JSON.stringify({
            kind,
            mobile,
            separateRoleJourney: true,
            finalState: mobile ? "erased" : "ended",
          }),
        );
      } finally {
        for (const context of contexts) await context.close();
      }
    });
  }
