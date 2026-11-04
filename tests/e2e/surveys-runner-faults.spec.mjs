import { test, expect } from "./csp-guard.mjs";
import { writeFileSync } from "node:fs";
const baseURL = process.env.LEONAID_E2E_BASE_URL;
const surveyId = process.env.SURVEY_KRAPFENTAXI_ID;
if (!baseURL || !surveyId) throw new Error("Published survey fixture required");
const saved = (page) =>
  expect(page.locator("[data-save-state]")).toHaveAttribute(
    "data-save-state",
    "saved",
  );

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
  const resumeUrl = page.url();
  const session = await context.storageState();
  // Fail the save at the request instead of with context.setOffline(true).
  // Closing a context detaches the DevTools session first, which lifts the
  // offline emulation while the page still runs. The page then receives an
  // "online" event and its retry can store the unsent text before the
  // renderer exits. A real closed tab never sends it.
  await page.route(
    (url) => url.pathname.startsWith(`/api/v1/public/surveys/${surveyId}/`),
    (route) =>
      route.request().method() === "PUT"
        ? route.abort("internetdisconnected")
        : route.continue(),
  );
  await page
    .locator("[data-name=delivery_feedback] textarea")
    .fill("Unsent text must not be restored");
  await expect(page.locator("[data-save-state]")).toHaveAttribute(
    "data-save-state",
    "error",
  );
  await expect(page.locator("[data-save-state]")).toContainText(
    "in diesem geöffneten Fenster",
  );
  await context.close();
  const restored = await browser.newContext({
    ignoreHTTPSErrors: true,
    storageState: session,
  });
  try {
    const fresh = await restored.newPage();
    await fresh.goto(resumeUrl);
    await expect(
      fresh.locator("[data-name=delivery_feedback] textarea"),
    ).toHaveValue("Unterwegs ohne Netz ergänzt");
    await expect(fresh.locator("[data-save-state]")).toHaveAttribute(
      "data-save-state",
      "saved",
    );
  } finally {
    await restored.close();
  }
});

test("two tabs reject a delayed stale save and retry a lost completion acknowledgement", async ({
  browser,
}) => {
  const id = process.env.SURVEY_CONDITION_COERCION_ID;
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const first = await context.newPage();
  let release;
  try {
    await first.goto(`${baseURL}/surveys/${id}`);
    await first
      .getByRole("button", { name: "Umfrage beginnen", exact: true })
      .click();
    const field = (page) => page.locator("[data-name=source] input");
    await field(first).fill("2");
    await saved(first);
    const participation = new URL(first.url()).searchParams.get(
      "participation",
    );
    const path = `/api/v1/public/surveys/${id}/participations/${participation}`;
    const second = await context.newPage();
    await second.goto(first.url());
    await expect(field(second)).toHaveValue("2");
    let queued;
    const waiting = new Promise((resolve) => {
      queued = resolve;
    });
    const held = new Promise((resolve) => {
      release = resolve;
    });
    const delayed = [];
    await first.route(`**${path}`, async (route) => {
      if (route.request().method() !== "PUT") return route.continue();
      delayed.push(route.request().postDataJSON());
      queued();
      await held;
      await route.continue();
    });
    await field(first).fill("3");
    await waiting;
    await field(second).fill("4");
    await saved(second);
    release();
    await expect(first.locator("[data-save-state]")).toHaveAttribute(
      "data-save-state",
      "conflict",
    );
    await expect(
      first.getByText("Ein anderes Fenster hat neuere Antworten gespeichert.", {
        exact: false,
      }),
    ).toBeVisible();
    expect(delayed).toHaveLength(1);
    const newer = await second.evaluate(
      async (path) => (await fetch(path)).json(),
      path,
    );
    expect(newer.response.answers).toEqual({ source: "4" });
    expect(newer.response.revision).toBe(delayed[0].expectedRevision + 1);
    first.on("dialog", (dialog) => dialog.accept());
    await first.reload();
    await expect(field(first)).toHaveValue("4");
    const completions = [];
    await second.route(`**${path}/complete`, async (route) => {
      completions.push(route.request().postDataJSON());
      const response = await route.fetch();
      expect(response.status()).toBe(200);
      if (completions.length === 1) await route.abort("failed");
      else await route.fulfill({ response });
    });
    await second
      .getByRole("button", { name: "Abschließen", exact: true })
      .click();
    await expect(second.locator("[data-save-state]")).toHaveAttribute(
      "data-save-state",
      "error",
    );
    await expect(
      second.getByRole("heading", {
        name: "Vielen Dank für Ihre Rückmeldung.",
      }),
    ).toHaveCount(0);
    const beforeRetry = await second.evaluate(
      async (path) => (await fetch(path)).json(),
      path,
    );
    expect(beforeRetry.response.status).toBe("completed");
    expect(beforeRetry.response.answers).toEqual({ source: "4" });
    await second
      .getByRole("button", { name: "Abschluss erneut bestätigen", exact: true })
      .click();
    await expect(
      second.getByRole("heading", {
        name: "Vielen Dank für Ihre Rückmeldung.",
      }),
    ).toBeVisible();
    expect(completions).toHaveLength(2);
    expect(completions[1]).toEqual(completions[0]);
    const afterRetry = await second.evaluate(
      async (path) => (await fetch(path)).json(),
      path,
    );
    expect(afterRetry.response).toEqual(beforeRetry.response);
    await second.evaluate(() => window.dispatchEvent(new Event("online")));
    await expect(
      second.getByRole("heading", {
        name: "Vielen Dank für Ihre Rückmeldung.",
      }),
    ).toBeVisible();
    writeFileSync(
      `${process.env.LEONAID_E2E_ARTIFACT_DIR}/survey-recovery.json`,
      JSON.stringify({
        survey: id,
        participation,
        revision: afterRetry.response.revision,
        answers: afterRetry.response.answers,
        operation: completions[0].operationId,
      }),
    );

    expect(new URL(second.url()).searchParams.get("participation")).toBe(
      participation,
    );
    await second.reload();
    await expect(
      second.getByRole("heading", {
        name: "Vielen Dank für Ihre Rückmeldung.",
      }),
    ).toBeVisible();
  } finally {
    release?.();
    await context.close();
  }
});
