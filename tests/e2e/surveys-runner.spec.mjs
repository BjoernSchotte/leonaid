import { test, expect } from "@playwright/test";
const baseURL = process.env.LEONAID_E2E_BASE_URL;
const surveyId = process.env.SURVEY_KRAPFENTAXI_ID;
if (!baseURL || !surveyId) throw new Error("Published survey fixture required");
const saved = (page) =>
  expect(page.locator("[data-save-state]")).toHaveAttribute(
    "data-save-state",
    "saved",
  );

test("acknowledged text survives closing mid-page and hidden follow-up is removed", async ({
  browser,
}) => {
  const viewport = process.env.SURVEY_MOBILE
    ? { width: 390, height: 844 }
    : { width: 1280, height: 960 };
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport,
  });
  let page = await context.newPage();
  await page.goto(`${baseURL}/surveys/${surveyId}`);
  await page.getByRole("button", { name: "Umfrage beginnen" }).click();
  await expect(page.locator("[data-name=delivery_rating]")).toBeVisible();
  expect(
    await page
      .locator(".sd-theme-root")
      .first()
      .evaluate((el) =>
        getComputedStyle(el)
          .getPropertyValue("--sjs2-color-project-brand-600")
          .trim(),
      ),
  ).toBe("#00338d");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page
    .locator("[data-name=delivery_rating]")
    .getByRole("radio")
    .first()
    .press("Space");
  const comment = page.locator("[data-name=delivery_feedback] textarea");
  await comment.fill("Bitte nächste Lieferung etwas früher – danke!");
  await saved(page);
  await expect(comment).toBeFocused();
  const url = page.url();
  const participationId = new URL(url).searchParams.get("participation");
  expect(participationId).toBeTruthy();
  const cookieState = await context.storageState();
  await page.screenshot({
    path: `${process.env.LEONAID_E2E_ARTIFACT_DIR}/surveys-mid-page.png`,
    fullPage: true,
  });
  await context.close();
  await new Promise((resolve) => setTimeout(resolve, 2200));
  const resumed = await browser.newContext({
    ignoreHTTPSErrors: true,
    storageState: cookieState,
    viewport,
  });
  page = await resumed.newPage();
  let writes = 0;
  page.on("request", (request) => {
    if (
      request.method() === "PUT" &&
      request.url().includes("/participations/")
    )
      writes++;
  });
  await page.goto(url);
  await expect(
    page.locator("[data-name=delivery_feedback] textarea"),
  ).toHaveValue("Bitte nächste Lieferung etwas früher – danke!");
  await saved(page);
  await page.waitForTimeout(650);
  expect(writes).toBe(0);
  const read = () =>
    page.evaluate(
      async ({ surveyId, participationId }) => {
        const response = await fetch(
          `/api/v1/public/surveys/${surveyId}/participations/${participationId}`,
        );
        return response.json();
      },
      { surveyId, participationId },
    );
  expect((await read()).response.status).toBe("partial");
  await page
    .locator("[data-name=delivery_rating]")
    .getByRole("radio")
    .last()
    .press("Space");
  await saved(page);
  await expect(page.locator("[data-name=delivery_feedback]")).toHaveCount(0);
  expect((await read()).response.answers).not.toHaveProperty(
    "delivery_feedback",
  );
  await page.getByRole("button", { name: "Weiter", exact: true }).click();
  await page
    .locator("[data-name=freshness]")
    .getByRole("radio")
    .first()
    .press("Space");
  await page.locator("[data-name=notes] textarea").fill("Notiz auf Seite zwei");
  await saved(page);
  await page.reload();
  await expect(page.locator("[data-name=notes] textarea")).toHaveValue(
    "Notiz auf Seite zwei",
  );
  expect((await read()).response.currentPage).toBe("experience");
  await page.getByRole("button", { name: "Zurück", exact: true }).click();
  await expect(page.locator("[data-name=delivery_feedback]")).toHaveCount(0);
  await page.getByRole("button", { name: "Weiter", exact: true }).click();
  await expect(page.locator("[data-name=notes] textarea")).toHaveValue(
    "Notiz auf Seite zwei",
  );
  await page.getByRole("button", { name: "Weiter", exact: true }).click();
  await page
    .locator("[data-name=nps]")
    .getByRole("radio")
    .last()
    .press("Space");
  await saved(page);
  await page.getByRole("button", { name: "Abschließen", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Vielen Dank für Ihre Rückmeldung." }),
  ).toBeVisible();
  expect((await read()).response.status).toBe("completed");
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Vielen Dank für Ihre Rückmeldung." }),
  ).toBeVisible();
  await resumed.close();
});

test("offline edits stay pending and retry successfully after reconnect", async ({
  browser,
}) => {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 390, height: 844 },
  });
  const page = await context.newPage();
  await page.goto(`${baseURL}/surveys/${surveyId}`);
  await page.getByRole("button", { name: "Umfrage beginnen" }).click();
  await page
    .locator("[data-name=delivery_rating]")
    .locator("label")
    .first()
    .click();
  const field = page.locator("[data-name=delivery_feedback] textarea");
  await field.fill("Erste gespeicherte Fassung");
  await saved(page);
  await context.setOffline(true);
  await field.fill("Unterwegs ohne Netz ergänzt");
  await expect(page.locator("[data-save-state]")).toHaveAttribute(
    "data-save-state",
    "error",
  );
  await expect(field).toHaveValue("Unterwegs ohne Netz ergänzt");
  await context.setOffline(false);
  await saved(page);
  await page.reload();
  await expect(
    page.locator("[data-name=delivery_feedback] textarea"),
  ).toHaveValue("Unterwegs ohne Netz ergänzt");
  await context.close();
});

test("minimum length, Unicode and case-insensitive conditions use persisted profile rules", async ({
  browser,
}) => {
  const id = process.env.SURVEY_VALIDATION_BOUNDARIES_ID;
  if (!id) throw new Error("Validation fixture required");
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  await page.goto(`${baseURL}/surveys/${id}`);
  await page.getByRole("button", { name: "Umfrage beginnen" }).click();
  const field = page.locator("[data-name=answer] input[type=text]");
  await field.fill("a");
  await expect(page.locator("[data-save-state]")).toHaveAttribute(
    "data-save-state",
    "error",
  );
  await page.getByRole("button", { name: "Abschließen", exact: true }).click();
  await expect(page.locator("[data-name=answer] .sd-error")).toBeVisible();
  await field.fill("YES");
  await expect(page.locator("[data-name=follow] textarea")).toBeVisible();
  await page.locator("[data-name=follow] textarea").fill("Begründung");
  await saved(page);
  await page.reload();
  await expect(page.locator("[data-name=follow] textarea")).toHaveValue(
    "Begründung",
  );
  await field.fill("😀a");
  await saved(page);
  await expect(page.locator("[data-name=follow]")).toHaveCount(0);
  const pid = new URL(page.url()).searchParams.get("participation");
  const state = await page.evaluate(
    async ({ id, pid }) => {
      const path = `/api/v1/public/surveys/${id}/participations/${pid}`;
      const before = await (await fetch(path)).json();
      const invalid = await fetch(path, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operationId: crypto.randomUUID(),
          expectedRevision: before.response.revision,
          answers: { answer: "😀ab" },
        }),
      });
      const after = await (await fetch(path)).json();
      return { before, after, rejected: invalid.status };
    },
    { id, pid },
  );
  expect(state.rejected).toBe(422);
  expect(state.after.response.revision).toBe(state.before.response.revision);
  expect(state.after.response.answers).toEqual({ answer: "😀a" });
  await page.getByRole("button", { name: "Abschließen", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Vielen Dank für Ihre Rückmeldung." }),
  ).toBeVisible();
  await context.close();
});

test("hidden pages clear chained answers through edits, direct saves and restoration", async ({
  browser,
}) => {
  const id = process.env.SURVEY_CONDITIONAL_PAGES_ID;
  if (!id) throw new Error("Conditional-page fixture required");
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  const input = (name) => page.locator(`[data-name=${name}] input[type=text]`);
  const next = () =>
    page.getByRole("button", { name: "Weiter", exact: true }).click();
  const back = () =>
    page.getByRole("button", { name: "Zurück", exact: true }).click();
  const choice = (name) =>
    page
      .locator("[data-name=topic]")
      .getByRole("radio", { name, exact: true })
      .press("Space");
  try {
    await page.goto(`${baseURL}/surveys/${id}`);
    await page.getByRole("button", { name: "Umfrage beginnen" }).click();
    await choice("Ja");
    await next();
    await input("detail").fill("Ursprüngliches Anliegen");
    await page
      .locator("[data-name=explanation] textarea")
      .fill("Alte Ergänzung");
    await next();
    await input("followup").fill("Alte Nachfrage");
    await next();
    await input("closing").fill("Abschluss bleibt erhalten");
    await saved(page);
    const pid = new URL(page.url()).searchParams.get("participation");
    const path = `/api/v1/public/surveys/${id}/participations/${pid}`;
    const read = () =>
      page.evaluate(async (path) => (await fetch(path)).json(), path);
    expect((await read()).response.answers).toEqual({
      topic: "yes",
      detail: "Ursprüngliches Anliegen",
      explanation: "Alte Ergänzung",
      followup: "Alte Nachfrage",
      closing: "Abschluss bleibt erhalten",
    });
    await back();
    await back();
    await back();
    await choice("Nein");
    await saved(page);
    expect((await read()).response.answers).toEqual({
      topic: "no",
      closing: "Abschluss bleibt erhalten",
    });
    await next();
    await expect(input("closing")).toHaveValue("Abschluss bleibt erhalten");
    await expect(input("followup")).toHaveCount(0);
    await saved(page);
    // A client bypassing UI cleanup still cannot reintroduce hidden data on the server.
    const direct = await page.evaluate(async (path) => {
      const before = await (await fetch(path)).json();
      const result = await fetch(path, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operationId: crypto.randomUUID(),
          expectedRevision: before.response.revision,
          currentPage: "end",
          answers: {
            ...before.response.answers,
            detail: "Injected stale",
            explanation: "Injected stale",
            followup: "Injected stale",
          },
        }),
      });
      return { status: result.status, after: await (await fetch(path)).json() };
    }, path);
    expect(direct.status).toBe(200);
    expect(direct.after.response.answers).toEqual({
      topic: "no",
      closing: "Abschluss bleibt erhalten",
    });
    let restoredWrites = 0;
    const countWrites = (request) => {
      if (
        request.method() === "PUT" &&
        request.url().includes(`/participations/${pid}`)
      )
        restoredWrites++;
    };
    page.on("request", countWrites);
    await page.reload();
    await expect(input("closing")).toHaveValue("Abschluss bleibt erhalten");
    await saved(page);
    await page.waitForTimeout(650);
    expect(restoredWrites).toBe(0);
    page.off("request", countWrites);
    expect((await read()).response.currentPage).toBe("end");
    await back();
    await choice("Ja");
    await next();
    await expect(input("detail")).toHaveValue("");
    await expect(page.locator("[data-name=explanation]")).toHaveCount(0);
    await next();
    await expect(page.locator("[data-name=detail] .sd-error")).toBeVisible();
    await input("detail").fill("Neues Anliegen");
    await expect(page.locator("[data-name=explanation] textarea")).toHaveValue(
      "",
    );
    await next();
    await expect(input("followup")).toHaveValue("");
    await input("followup").fill("Neue Nachfrage");
    await next();
    await saved(page);
    await page
      .getByRole("button", { name: "Abschließen", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Vielen Dank für Ihre Rückmeldung." }),
    ).toBeVisible();
    const completed = (await read()).response;
    expect(completed.status).toBe("completed");
    expect(completed.answers).toEqual({
      topic: "yes",
      detail: "Neues Anliegen",
      followup: "Neue Nachfrage",
      closing: "Abschluss bleibt erhalten",
    });
  } finally {
    await context.close();
  }
});
