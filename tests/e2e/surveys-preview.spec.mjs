import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

const base = process.env.LEONAID_E2E_BASE_URL;
test("backend timeout changes preserve existing participation and preview stays outside real analysis", async ({
  browser,
}) => {
  const { surveyId: sid } = JSON.parse(
    readFileSync(
      `${process.env.LEONAID_E2E_ARTIFACT_DIR}/preview-state.json`,
      "utf8",
    ),
  );
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1440, height: 1000 },
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: process.env.SURVEY_ADMIN_SESSION,
      url: base,
      secure: true,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  const page = await context.newPage();
  await page.goto(`${base}/admin/surveys/${sid}`);
  const publicWrites = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/v1/public/surveys/") && r.method() !== "GET")
      publicWrites.push(r.url());
  });
  await page.getByRole("button", { name: "Vorschau", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Synthetic response", exact: true })
    .fill("PREVIEW_ONLY");
  await page.getByRole("button", { name: "Abschließen", exact: true }).click();
  await expect(page.getByText(/Vielen Dank/).last()).toBeVisible();
  await page
    .getByRole("button", { name: "Zurück zum Editor", exact: true })
    .click();
  expect(publicWrites).toHaveLength(0);
  async function startAndSave(answer) {
    return page.evaluate(
      async ({ sid, answer }) => {
        const path = `/api/v1/public/surveys/${sid}/participations`;
        const response = await fetch(path, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            operationId: crypto.randomUUID(),
            resumeSecret: crypto.randomUUID() + crypto.randomUUID(),
          }),
        });
        if (!response.ok) throw new Error(`start ${response.status}`);
        const p = await response.json();
        const saved = await fetch(`${path}/${p.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            operationId: crypto.randomUUID(),
            expectedRevision: 1,
            answers: { answer },
          }),
        });
        if (!saved.ok) throw new Error(`save ${saved.status}`);
        return p;
      },
      { sid, answer },
    );
  }
  const old = await startAndSave("REAL_OLD");
  expect(old.inactivityTimeoutSeconds).toBe(60);
  await page
    .getByText("Teilantworten nach Inaktivität", { exact: true })
    .click();
  await page.getByLabel("Abweichender Zeitraum in Sekunden").fill("1");
  await page
    .getByRole("button", { name: "Zeitraum speichern", exact: true })
    .click();
  await expect(
    page.getByText("Zeitraum wurde gespeichert.", { exact: true }),
  ).toBeVisible();
  const recent = await startAndSave("REAL_NEW");
  expect(recent.inactivityTimeoutSeconds).toBe(1);
  async function participation(id) {
    return page.evaluate(
      async ({ sid, id }) =>
        await (
          await fetch(`/api/v1/public/surveys/${sid}/participations/${id}`)
        ).json(),
      { sid, id },
    );
  }
  await expect
    .poll(async () => (await participation(recent.id)).response.status)
    .toBe("partial");
  const restoredOld = await participation(old.id);
  expect(restoredOld.inactivityTimeoutSeconds).toBe(60);
  expect(restoredOld.response.status).toBe("in_progress");
  expect(restoredOld.response.answers).toEqual({ answer: "REAL_OLD" });
  await page.evaluate(
    async ({ sid, id }) => {
      const response = await fetch(
        `/api/v1/public/surveys/${sid}/participations/${id}/complete`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            operationId: crypto.randomUUID(),
            expectedRevision: 2,
          }),
        },
      );
      if (!response.ok) throw new Error(`complete ${response.status}`);
    },
    { sid, id: old.id },
  );
  await page.reload();
  await page.getByText("Antworten auswerten", { exact: true }).click();
  const runAnalysis = async (isTest) => {
    await page
      .getByRole("combobox", { name: "Antwortquelle", exact: true })
      .first()
      .selectOption(isTest ? "test" : "real");
    const response = page.waitForResponse(
      (r) =>
        r.url().endsWith(`/surveys/${sid}/analysis`) &&
        r.request().method() === "POST",
    );
    await page
      .getByRole("button", { name: "Auswertung erstellen", exact: true })
      .click();
    const result = await response;
    expect(result.status()).toBe(200);
    return result.json();
  };
  const real = await runAnalysis(false);
  expect(real.filter.isTest).toBe(false);
  expect(real.participationCount).toBe(2);
  const simulated = await runAnalysis(true);
  expect(simulated.filter.isTest).toBe(true);
  expect(simulated.participationCount).toBe(1);
  await context.close();
});
