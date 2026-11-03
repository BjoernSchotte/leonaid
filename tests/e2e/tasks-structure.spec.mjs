import { test, expect } from "./csp-guard.mjs";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";

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

test("priority, a new tag and a checklist are saved in one revision and shown on the PWA", async ({
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
  await page.goto(`${baseURL}/admin/tasks/${list.id}?task=${task.id}`);
  const panel = page.getByRole("form", {
    name: "Priorität, Tags und Checkliste",
  });
  await expect(panel).toBeVisible();

  await panel.getByLabel("Hohe Priorität").check();
  const tagTitle = `Aufbau${randomUUID().slice(0, 6)}`;
  await panel.getByLabel("Neuer Tag").fill(tagTitle);
  await panel.getByRole("button", { name: "Tag anlegen" }).click();
  await expect(panel.getByLabel(tagTitle)).toBeChecked();
  await panel.getByLabel("Neuer Schritt").fill("Tische holen");
  await panel.getByRole("button", { name: "Schritt hinzufügen" }).click();
  await panel.getByLabel("Neuer Schritt").fill("Strom prüfen");
  await panel.getByRole("button", { name: "Schritt hinzufügen" }).click();
  await panel.getByLabel("Schritt 1 erledigt").check();
  await panel.getByRole("button", { name: "Struktur speichern" }).click();
  await expect(panel.getByRole("status")).toHaveText("Struktur gespeichert.");

  const saved = await (
    await web.request.get(`${baseURL}/api/v1/tasks/${task.id}`)
  ).json();
  expect(saved.revision).toBe(task.revision + 1);
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
  await panel.getByRole("button", { name: "Struktur speichern" }).click();
  await expect(panel.getByText(/inzwischen geändert/)).toBeVisible();
  await expect(panel.getByLabel("Hohe Priorität")).not.toBeChecked();
  await web.close();

  const mobile = await signedInContext(browser, 390);
  const app = await mobile.newPage();
  await app.goto(`${baseURL}/app/tasks/${list.id}`);
  const row = app.locator(`#task-metadata-${task.id}`);
  await expect(row).toContainText("Hohe Priorität");
  await expect(row).toContainText(`#${tagTitle}`);
  await expect(row).toContainText("Checkliste 1/2");
  expect(
    await app.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await mobile.close();
  expect(violations).toEqual([]);
});
