import { test, expect } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
const base = process.env.LEONAID_E2E_BASE_URL;
const proof = process.env.LEONAID_E2E_ARTIFACT_DIR;

async function context(browser, width, token, storageState) {
  const result = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width, height: 960 },
    storageState,
  });
  if (token)
    await result.addCookies([
      {
        name: "__Host-leonaid_session",
        value: token,
        url: base,
        secure: true,
        httpOnly: true,
        sameSite: "Lax",
      },
    ]);
  return result;
}
async function saved(page) {
  await expect(page.locator("[data-save-state]")).toHaveAttribute(
    "data-save-state",
    "saved",
  );
}
async function rate(page, name, value) {
  const question = page.locator(`[data-name=${name}]`);
  await expect(async () => {
    const dropdown = question.getByRole("combobox");
    if (await dropdown.isVisible()) {
      await dropdown.click({ timeout: 1000 });
      await page
        .getByRole("option", { name: String(value), exact: true })
        .click({ timeout: 1000 });
      await expect(dropdown).toContainText(String(value), { timeout: 1000 });
    } else {
      const radio = question.locator(`input[type=radio][value="${value}"]`);
      await radio.press("Space", { timeout: 1000 });
      await expect(radio).toBeChecked({ timeout: 1000 });
    }
  }).toPass({ timeout: 15000, intervals: [100, 250] });
}
async function invite(page, request, sid, suffix) {
  await page.reload();
  await page.getByText(/^Einladungen \(/).click();
  const email = `journey-${sid}-${suffix}@example.com`;
  await page.getByLabel("E-Mail des Empfängers", { exact: true }).fill(email);
  await page
    .getByRole("button", { name: "Einladung senden", exact: true })
    .click();
  let mail;
  await expect
    .poll(
      async () => {
        const list = await (
          await request.get("http://mailpit:8025/mail/api/v1/messages")
        ).json();
        mail = list.messages.find((m) =>
          m.To.some((to) => to.Address === email),
        );
        return !!mail;
      },
      { timeout: 30000 },
    )
    .toBe(true);
  const body = await (
    await request.get(`http://mailpit:8025/mail/api/v1/message/${mail.ID}`)
  ).json();
  const url = new URL(
    body.Text.match(/https:\/\/[^\s]+#invitation=[A-Za-z0-9_-]+/)[0],
  );
  return `${base}${url.pathname}${url.hash}`;
}
for (const template of ["krapfentaxi", "golf"])
  for (const width of [1440, 390]) {
    test(`${template} complete author-to-erasure journey at ${width}`, async ({
      browser,
      request,
    }) => {
      test.setTimeout(240000);
      const admin = await context(
        browser,
        width,
        process.env.SURVEY_ADMIN_SESSION,
      );
      const outsider = await context(
        browser,
        width,
        process.env.SURVEY_MEMBER_SESSION,
      );
      let recipient = await context(browser, width);
      const newer = await context(browser, width);
      const page = await admin.newPage();
      const marker = `Journey ${template} ${width} – bestätigt 🌱`;
      const outputs = [];
      try {
        await page.goto(`${base}/admin/surveys/new`);
        await page
          .getByLabel("Titel der Umfrage", { exact: true })
          .fill(`Journey ${template} ${width}`);
        await page
          .getByLabel("Fragebogenvorlage", { exact: true })
          .selectOption(template);
        await page
          .getByRole("button", { name: "Umfrage erstellen", exact: true })
          .click();
        const editor = page.getByRole("region", {
          name: "Fragebogen bearbeiten",
        });
        await expect(editor).toBeVisible();
        const sid = page.url().split("/").at(-1);
        const api = `${base}/api/v1/surveys/${sid}`;
        const firstQuestion = () =>
          editor
            .getByRole("list", { name: "Fragen auf dieser Seite" })
            .locator("li")
            .first()
            .getByRole("button")
            .first();
        await firstQuestion().click();
        await editor
          .getByLabel("Fragetitel", { exact: true })
          .fill("Journey question version one");
        await expect(page.locator("[data-draft-state]")).toHaveAttribute(
          "data-draft-state",
          "saved",
        );
        await page
          .getByText("Teilantworten nach Inaktivität", { exact: true })
          .click();
        await page.getByLabel("Abweichender Zeitraum in Sekunden").fill("2");
        await page
          .getByRole("button", { name: "Zeitraum speichern", exact: true })
          .click();
        await expect(
          page.getByText("Zeitraum wurde gespeichert.", { exact: true }),
        ).toBeVisible();
        if (template === "golf") {
          await page.getByText("Zugang zur Umfrage", { exact: true }).click();
          await page
            .getByRole("combobox", { name: "Zugangsmodus", exact: true })
            .selectOption("invitation");
          await page
            .getByRole("button", {
              name: "Zugangsmodus speichern",
              exact: true,
            })
            .click();
          await expect(
            page.getByText("Zugangsmodus wurde gespeichert.", { exact: true }),
          ).toBeVisible();
        }
        await editor
          .getByRole("button", { name: "Veröffentlichen", exact: true })
          .click();
        await expect(page.locator("[data-survey-status]")).toHaveAttribute(
          "data-survey-status",
          "active",
        );
        const version1 = (await (await admin.request.get(api)).json())
          .publishedVersionId;
        expect((await outsider.request.get(api)).status()).toBe(404);
        const outsiderPage = await outsider.newPage();
        await outsiderPage.goto(`${base}/admin/surveys/${sid}`);
        await expect(outsiderPage.getByRole("alert")).toBeVisible();
        await expect(
          outsiderPage.getByRole("region", { name: "Fragebogen bearbeiten" }),
        ).toHaveCount(0);
        expect(
          (
            await outsider.request.post(`${api}/analysis`, {
              data: {
                operationId: "outsider",
                filter: { versionId: version1 },
              },
            })
          ).status(),
        ).toBe(404);
        const url =
          template === "golf"
            ? await invite(page, request, sid, "first")
            : `${base}/surveys/${sid}`;
        let respondent = await recipient.newPage();
        await respondent.goto(url);
        await respondent
          .getByRole("button", { name: "Umfrage beginnen", exact: true })
          .click();
        if (template === "krapfentaxi")
          await rate(respondent, "delivery_rating", 5);
        else {
          const radios = respondent.locator(
            '[data-name=event_rating] input[type=radio][value="3"]',
          );
          await expect(radios).toHaveCount(3);
          for (let i = 0; i < 3; i++) await radios.nth(i).press("Space");
        }
        await respondent
          .getByRole("button", { name: "Weiter", exact: true })
          .click();
        if (template === "krapfentaxi") {
          await respondent
            .locator('[data-name=freshness] input[value="fresh"]')
            .press("Space");
          await respondent.locator("[data-name=notes] textarea").fill(marker);
        } else {
          await respondent
            .locator('[data-name=improvements] input[value="food"]')
            .press("Space");
          await respondent
            .locator("[data-name=food_feedback] textarea")
            .fill(marker);
        }
        await saved(respondent);
        const resumeUrl = respondent.url();
        const pid = new URL(resumeUrl).searchParams.get("participation");
        expect(pid).toBeTruthy();
        const responseApi = `${base}/api/v1/public/surveys/${sid}/participations/${pid}`;
        const before = await (await recipient.request.get(responseApi)).json();
        expect(before.version.id).toBe(version1);
        expect(
          before.response.answers[
            template === "golf" ? "food_feedback" : "notes"
          ],
        ).toBe(marker);
        const storage = await recipient.storageState();
        await recipient.close();
        // Publish through the editor while the original browser context is gone.
        await page.goto(`${base}/admin/surveys/${sid}`);
        await firstQuestion().click();
        await editor
          .getByLabel("Fragetitel", { exact: true })
          .fill("Journey question version two");
        await expect(page.locator("[data-draft-state]")).toHaveAttribute(
          "data-draft-state",
          "saved",
        );
        await editor
          .getByRole("button", { name: "Veröffentlichen", exact: true })
          .click();
        await expect
          .poll(
            async () =>
              (await (await admin.request.get(api)).json()).publishedVersionId,
          )
          .not.toBe(version1);
        const version2 = (await (await admin.request.get(api)).json())
          .publishedVersionId;
        recipient = await context(browser, width, undefined, storage);
        await expect
          .poll(
            async () =>
              (await (await recipient.request.get(responseApi)).json()).response
                .status,
          )
          .toBe("partial");
        respondent = await recipient.newPage();
        await respondent.goto(resumeUrl);
        await expect(
          respondent.locator(
            `[data-name=${template === "golf" ? "food_feedback" : "notes"}] textarea`,
          ),
        ).toHaveValue(marker);
        const restored = await (
          await recipient.request.get(responseApi)
        ).json();
        expect(restored.response.answers).toEqual(before.response.answers);
        expect(restored.response.revision).toBe(before.response.revision);
        expect(restored.version.id).toBe(version1);
        expect(restored.version.definition.pages[0].elements[0].title).toBe(
          "Journey question version one",
        );
        const nextUrl =
          template === "golf"
            ? await invite(page, request, sid, "second")
            : `${base}/surveys/${sid}`;
        const next = await newer.newPage();
        await next.goto(nextUrl);
        await next
          .getByRole("button", { name: "Umfrage beginnen", exact: true })
          .click();
        await expect
          .poll(() => new URL(next.url()).searchParams.get("participation"))
          .toBeTruthy();
        const newState = await (
          await newer.request.get(
            `${base}/api/v1/public/surveys/${sid}/participations/${new URL(next.url()).searchParams.get("participation")}`,
          )
        ).json();
        expect(newState.version.id).toBe(version2);
        expect(newState.version.definition.pages[0].elements[0].title).toBe(
          "Journey question version two",
        );
        await respondent
          .getByRole("button", { name: "Weiter", exact: true })
          .click();
        if (template === "krapfentaxi") {
          await rate(respondent, "nps", 10);
          await respondent
            .locator("[data-name=nickname] input")
            .fill("Synthetic participant");
        } else {
          await respondent
            .locator("[data-name=return] .sd-dropdown__input-prefix-wrapper")
            .click();
          const yes = respondent.getByRole("option", {
            name: "yes",
            exact: true,
          });
          await expect(yes).toBeVisible();
          // Playwright's locator auto-scroll dismisses this fixed SurveyJS
          // popup. Hit-test the visible option before a real pointer click.
          let point;
          await expect
            .poll(async () => {
              point = await yes.evaluate((option) => {
                const rect = option.getBoundingClientRect();
                const x = rect.x + rect.width / 2;
                const y = rect.y + rect.height / 2;
                return {
                  x,
                  y,
                  reachable: option.contains(document.elementFromPoint(x, y)),
                };
              });
              return point.reachable;
            })
            .toBe(true);
          await respondent.mouse.click(point.x, point.y);
          await expect(
            respondent.locator("[data-name=return]").getByRole("combobox"),
          ).toHaveValue("yes");
          await respondent.locator("[data-name=handicap] input").fill("18");
          await respondent
            .locator("[data-name=preferred_date] input")
            .fill("2026-10-10");
        }
        await saved(respondent);
        await respondent
          .getByRole("button", { name: "Abschließen", exact: true })
          .click();
        await expect(
          respondent.getByRole("heading", { name: "Vielen Dank" }),
        ).toBeVisible();
        const completed = await (
          await recipient.request.get(responseApi)
        ).json();
        expect(completed.response.status).toBe("completed");
        expect(completed.version.id).toBe(version1);
        await page.goto(`${base}/admin/surveys/${sid}`);
        await page.getByText("Antworten auswerten", { exact: true }).click();
        await page.getByLabel("Fragebogen-Version").selectOption(version1);
        const snapshotEvent = page.waitForResponse(
          (r) =>
            r.url() === `${api}/analysis` && r.request().method() === "POST",
        );
        await page
          .getByRole("button", { name: "Auswertung erstellen", exact: true })
          .click();
        const snapshot = await (await snapshotEvent).json();
        expect(snapshot.versionNumber).toBe(1);
        expect(snapshot.participationCount).toBe(1);
        await expect(
          page.getByText("Ausgewerteter Stand: Version 1", { exact: false }),
        ).toBeVisible();
        const results = page.locator(`[data-snapshot-id="${snapshot.id}"]`);
        await expect(results).toBeVisible();
        for (const question of snapshot.questions) {
          const section = results.locator(
            `[data-question-id="${question.questionId}"]`,
          );
          await expect(
            section.getByRole("heading", { name: question.title, exact: true }),
          ).toBeVisible();
          const counts = await section
            .locator(":scope > .survey-analytics-counts dd")
            .allTextContents();
          expect(counts).toEqual(
            ["relevant", "answered", "unanswered", "hidden", "invalid"].map(
              (k) => String(question[k]),
            ),
          );
        }
        await results
          .locator(".survey-analytics-table > summary")
          .first()
          .click();
        await expect(results.getByRole("table").first()).toBeVisible();
        const panel = page.getByRole("region", {
          name: "Auswertung exportieren",
          exact: true,
        });
        for (const [product, label] of Object.entries({
          analysis_xlsx: "Auswertung · Excel",
          analysis_pdf: "Auswertung · PDF",
          responses_csv: "Einzelantworten · CSV",
          responses_xlsx: "Einzelantworten · Excel",
        })) {
          const row = panel.getByRole("listitem", { name: label, exact: true });
          const jobEvent = page.waitForResponse(
            (r) =>
              r.url() === `${api}/exports` && r.request().method() === "POST",
          );
          await row
            .getByRole("button", { name: "Datei erstellen", exact: true })
            .click();
          const job = await (await jobEvent).json();
          expect(job.snapshotId).toBe(snapshot.id);
          await expect(
            row.getByText("Bereit zum Herunterladen", { exact: true }),
          ).toBeVisible({ timeout: 45000 });
          const downloaded = page.waitForEvent("download");
          await row
            .getByRole("button", { name: "Herunterladen", exact: true })
            .click();
          const download = await downloaded;
          expect(await download.failure()).toBeNull();
          const bytes = readFileSync(await download.path());
          expect(bytes.length).toBeGreaterThan(100);
          if (product.endsWith("xlsx"))
            expect(bytes.subarray(0, 2).toString()).toBe("PK");
          if (product.endsWith("pdf"))
            expect(bytes.subarray(0, 5).toString()).toBe("%PDF-");
          if (product.endsWith("csv")) {
            expect(bytes.toString()).toContain(marker);
            expect(bytes.toString()).toContain(snapshot.id);
          }
          expect(
            (
              await outsider.request.get(`${api}/exports/${job.id}/download`)
            ).status(),
          ).toBe(404);
          const extension = product.split("_").at(-1);
          writeFileSync(
            `${proof}/journey-${template}-${width}-${product}.${extension}`,
            bytes,
          );
          outputs.push({ product, jobId: job.id, bytes: bytes.length });
        }
        await page
          .getByRole("button", { name: "Teilnahme beenden", exact: true })
          .click();
        await expect(page.locator("[data-survey-status]")).toHaveAttribute(
          "data-survey-status",
          "ended",
        );
        await page
          .getByRole("button", { name: "Archivieren", exact: true })
          .click();
        await expect(page.locator("[data-survey-status]")).toHaveAttribute(
          "data-survey-status",
          "archived",
        );
        await page
          .getByRole("button", {
            name: "In Papierkorb verschieben",
            exact: true,
          })
          .click();
        await page
          .getByRole("button", {
            name: "Jetzt in Papierkorb verschieben",
            exact: true,
          })
          .click();
        await expect(page.locator("[data-survey-status]")).toHaveAttribute(
          "data-survey-status",
          "deleted",
        );
        await page
          .getByRole("button", { name: "Endgültig löschen", exact: true })
          .click();
        await page
          .getByRole("checkbox", {
            name: "Ich möchte diese Umfrage",
            exact: false,
          })
          .check();
        await page
          .getByRole("button", {
            name: "Löschung jetzt beauftragen",
            exact: true,
          })
          .click();
        await expect(
          page.getByRole("region", {
            name: "Endgültige Löschung",
            exact: true,
          }),
        ).toContainText("wurde endgültig gelöscht", { timeout: 60000 });
        expect((await recipient.request.get(responseApi)).status()).toBe(404);
        for (const job of outputs)
          expect(
            (
              await admin.request.get(`${api}/exports/${job.jobId}/download`)
            ).status(),
          ).toBe(404);
        writeFileSync(
          `${proof}/journey-${template}-${width}.json`,
          JSON.stringify({
            template,
            width,
            sid,
            pid,
            version1,
            version2,
            snapshotId: snapshot.id,
            snapshot,
            answers: completed.response.answers,
            exports: outputs,
            partialResumeAndVersionIsolation: true,
            outsiderDenied: true,
            erasureCompleted: true,
          }),
        );
      } finally {
        await admin.close();
        await outsider.close();
        await recipient.close();
        await newer.close();
      }
    });
  }
