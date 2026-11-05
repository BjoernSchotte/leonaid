import { test, expect } from "./csp-guard.mjs";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { taskPane, taskRow } from "./task-list.mjs";

const fixture = JSON.parse(
  readFileSync(process.env.LEONAID_MODULE_FIXTURE, "utf8"),
);
const baseURL = process.env.LEONAID_E2E_BASE_URL;

async function signedInContext(browser, width) {
  const context = await browser.newContext({
    viewport: { width, height: 844 },
    ignoreHTTPSErrors: true,
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: fixture.sessions[0],
      url: baseURL,
      secure: true,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  return context;
}

async function createListAndTask(context) {
  const headers = { Origin: baseURL };
  const list = await (
    await context.request.post(`${baseURL}/api/v1/task-lists`, {
      headers,
      data: {
        title: `Struktur ${randomUUID()}`,
        actionId: null,
        idempotencyKey: randomUUID(),
      },
    })
  ).json();
  const response = await context.request.post(
    `${baseURL}/api/v1/task-lists/${list.id}/tasks`,
    {
      headers,
      data: {
        title: "Stände aufbauen",
        description: "",
        assigneeUserId: null,
        epicId: null,
        dueAt: null,
        deferredUntil: null,
        idempotencyKey: randomUUID(),
      },
    },
  );
  expect(response.ok()).toBe(true);
  return { list, task: await response.json() };
}

test("steps save at once; priority and a new Schlagwort save together and show on the PWA", async ({
  browser,
}) => {
  const violations = [];
  const web = await signedInContext(browser, 1440);
  const { list, task } = await createListAndTask(web);
  const page = await web.newPage();
  page.on("console", (message) => {
    if (/Content Security Policy/i.test(message.text()))
      violations.push(message.text());
  });
  // An old deep link opens the task in the pane.
  await page.goto(`${baseURL}/admin/tasks/${list.id}?task=${task.id}`);
  await expect(page).toHaveURL(new RegExp(`open=${task.id}`));
  const pane = taskPane(page, task.id);
  // Steps live in "Schritte": each add and tick is saved at once.
  const steps = pane.locator(".steps-add");
  await steps.getByLabel("Neuer Schritt").fill("Tische holen");
  await steps.getByRole("button", { name: "Schritt hinzufügen" }).click();
  await expect(
    pane.locator(".steps").getByRole("checkbox", { name: "Tische holen" }),
  ).toBeVisible();
  await steps.getByLabel("Neuer Schritt").fill("Strom prüfen");
  await steps.getByRole("button", { name: "Schritt hinzufügen" }).click();
  const first = pane
    .locator(".steps")
    .getByRole("checkbox", { name: "Tische holen" });
  await expect(
    pane.locator(".steps").getByRole("checkbox", { name: "Strom prüfen" }),
  ).toBeEnabled();
  await first.check();
  await expect(first).toBeChecked();
  // The list row follows the saved steps (the refetched revision).
  await expect(taskRow(page, task.id).locator(".row-secondary")).toContainText(
    "1/2 Schritte",
  );

  // Priority and Schlagworte are saved together in their own form.
  const panel = pane.getByRole("form", { name: "Priorität und Schlagworte" });
  await expect(panel).toBeVisible();
  await panel.getByLabel("Hohe Priorität").check();
  const tagTitle = `Aufbau${randomUUID().slice(0, 6)}`;
  await panel.getByLabel("Neues Schlagwort").fill(tagTitle);
  await panel.getByRole("button", { name: "Schlagwort anlegen" }).click();
  await expect(panel.getByLabel(tagTitle)).toBeChecked();
  await panel.getByRole("button", { name: "Speichern", exact: true }).click();
  await expect(panel.getByRole("status")).toHaveText("Gespeichert.");
  // The step changes did not make this save a conflict.
  await expect(panel.getByText(/inzwischen geändert/)).toHaveCount(0);

  const saved = await (
    await web.request.get(`${baseURL}/api/v1/tasks/${task.id}`)
  ).json();
  // Two added steps, one tick, then priority and tag: four revisions.
  expect(saved.revision).toBe(task.revision + 4);
  expect(saved.priority).toBe("high");
  expect(saved.tags.map((tag) => tag.title)).toEqual([tagTitle]);
  expect(saved.checklist.map((step) => [step.text, step.done])).toEqual([
    ["Tische holen", true],
    ["Strom prüfen", false],
  ]);

  // A stale second save keeps the draft and reports the conflict.
  await panel.getByLabel("Hohe Priorität").uncheck();
  await web.request.put(`${baseURL}/api/v1/tasks/${task.id}/structure`, {
    headers: { Origin: baseURL },
    data: {
      idempotencyKey: randomUUID(),
      expectedRevision: saved.revision,
      priority: "high",
      tagIds: saved.tags.map((tag) => tag.id),
      checklist: saved.checklist,
    },
  });
  await panel.getByRole("button", { name: "Speichern", exact: true }).click();
  await expect(panel.getByText(/inzwischen geändert/)).toBeVisible();
  await expect(panel.getByLabel("Hohe Priorität")).not.toBeChecked();
  await web.close();

  const mobile = await signedInContext(browser, 390);
  const app = await mobile.newPage();
  await app.goto(`${baseURL}/app/tasks/${list.id}`);
  const row = taskRow(app, task.id);
  await expect(
    row.locator('.flag-high[aria-label="Hohe Priorität"]'),
  ).toBeVisible();
  await expect(row.locator(".row-secondary")).toContainText(`#${tagTitle}`);
  await expect(row.locator(".row-secondary")).toContainText("1/2 Schritte");
  expect(
    await app.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await mobile.close();
  expect(violations).toEqual([]);
});
