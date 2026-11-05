import { test, expect } from "./csp-guard.mjs";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { openTask, taskRowLink } from "./task-list.mjs";

const fixture = JSON.parse(
  readFileSync(process.env.LEONAID_MODULE_FIXTURE, "utf8"),
);
const baseURL = process.env.LEONAID_E2E_BASE_URL;

async function signedInContext(browser, session, width) {
  const context = await browser.newContext({
    viewport: { width, height: 844 },
    ignoreHTTPSErrors: true,
    timezoneId: "Europe/Berlin",
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: fixture.sessions[session],
      url: baseURL,
      secure: true,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  return context;
}

async function createPlanningFixture(context) {
  const headers = { Origin: baseURL };
  const listResponse = await context.request.post(
    `${baseURL}/api/v1/task-lists`,
    {
      headers,
      data: {
        title: `S5 Persönliche Planung ${randomUUID()}`,
        actionId: null,
        idempotencyKey: randomUUID(),
      },
    },
  );
  expect(listResponse.ok()).toBe(true);
  let list = await listResponse.json();
  const grant = await context.request.put(
    `${baseURL}/api/v1/task-lists/${list.id}/members`,
    {
      headers,
      data: {
        idempotencyKey: randomUUID(),
        expectedRevision: list.revision,
        userId: fixture.users[1],
        access: "viewer",
      },
    },
  );
  expect(grant.ok()).toBe(true);
  list = await grant.json();
  const tasks = [];
  for (const [title, dueAt] of [
    ["S5 Persönlich geplant und fällig", new Date().toISOString()],
    ["S5 Nur als Fälligkeitshinweis", new Date().toISOString()],
  ]) {
    const response = await context.request.post(
      `${baseURL}/api/v1/task-lists/${list.id}/tasks`,
      {
        headers,
        data: {
          title,
          description: "",
          assigneeUserId: fixture.users[0],
          epicId: null,
          dueAt,
          deferredUntil: null,
          idempotencyKey: randomUUID(),
        },
      },
    );
    expect(response.ok()).toBe(true);
    tasks.push(await response.json());
  }
  return { list, tasks };
}

test("S5 personal planning stays private and usable for owners and readers", async ({
  browser,
}, testInfo) => {
  const owner = await signedInContext(browser, 0, 1440);
  const reader = await signedInContext(browser, 1, 390);
  const { list, tasks } = await createPlanningFixture(owner);
  const today = await owner.newPage();
  const plannedOn = await today.evaluate(() => {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  });
  await today.goto(`${baseURL}/admin/tasks/${list.id}`);
  const ownerPane = await openTask(today, { id: tasks[0].id });
  const ownerPlan = ownerPane.locator(".task-plan-form");
  await expect(ownerPlan.getByRole("heading")).toHaveText(
    "Persönliche Planung",
  );
  await expect(ownerPlan).toContainText("Nur Sie sehen diese Einordnung.");
  await ownerPlan.getByLabel("Einordnung").selectOption("scheduled");
  await ownerPlan.getByLabel("Geplant für").fill(plannedOn);
  await ownerPlan.getByRole("button", { name: "Planung speichern" }).click();
  await expect(ownerPlan.getByRole("status")).toHaveText(
    "Planung gespeichert.",
  );
  // The row shows the plan right away.
  await expect(
    today.locator(`.row:has([data-task-row="${tasks[0].id}"]) .task-plan`),
  ).toHaveText("Heute");

  // The old "Mein Heute" link opens "Mein Plan" with today's buckets.
  await today.goto(`${baseURL}/admin/tasks?scope=mine&view=plan-today`);
  await expect(today).toHaveURL(/f\.plan=today&f\.plan=due/);
  await expect(
    today
      .getByRole("navigation", { name: "Gespeicherte Ansichten" })
      .getByRole("button", { name: /^Mein Plan/ }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    today.locator(".group-header", { hasText: /^Heute\d/ }),
  ).toBeVisible();
  await expect(
    today.locator(".group-header", { hasText: "Bis heute fällig" }),
  ).toBeVisible();
  await expect(taskRowLink(today, { id: tasks[0].id })).toHaveCount(1);
  await expect(taskRowLink(today, { id: tasks[1].id })).toHaveCount(1);
  await today.screenshot({
    path: testInfo.outputPath("s5-desktop-personal-today.png"),
    fullPage: false,
  });

  const readerPage = await reader.newPage();
  await readerPage.goto(`${baseURL}/app/tasks/${list.id}`);
  const readerPane = await openTask(readerPage, { id: tasks[0].id });
  await expect(readerPane.locator("form.task-editor")).toHaveCount(0);
  const readerPlan = readerPane.locator(".task-plan-form");
  await expect(readerPlan).toContainText("Nur du siehst diese Einordnung.");
  await readerPlan.getByLabel("Einordnung").selectOption("someday");
  await readerPlan.getByRole("button", { name: "Planung speichern" }).click();
  await expect(readerPlan.getByRole("status")).toHaveText(
    "Planung gespeichert.",
  );
  expect(
    await readerPage.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await readerPage.screenshot({
    path: testInfo.outputPath("s5-pwa-reader-planning.png"),
    fullPage: false,
  });

  await readerPage.goto(`${baseURL}/app/tasks`);
  await expect(
    readerPage.locator(".group-header", { hasText: "Irgendwann" }),
  ).toBeVisible();
  await expect(taskRowLink(readerPage, { id: tasks[0].id })).toBeVisible();
  const ownerPlanRead = await owner.request.get(
    `${baseURL}/api/v1/tasks/${tasks[0].id}/plan`,
  );
  const readerPlanRead = await reader.request.get(
    `${baseURL}/api/v1/tasks/${tasks[0].id}/plan`,
  );
  expect((await ownerPlanRead.json()).state).toBe("scheduled");
  expect((await readerPlanRead.json()).state).toBe("someday");

  const revoke = await owner.request.put(
    `${baseURL}/api/v1/task-lists/${list.id}/members`,
    {
      headers: { Origin: baseURL },
      data: {
        idempotencyKey: randomUUID(),
        expectedRevision: list.revision,
        userId: fixture.users[1],
        access: null,
      },
    },
  );
  expect(revoke.ok()).toBe(true);
  expect(
    (
      await reader.request.get(`${baseURL}/api/v1/tasks/${tasks[0].id}/plan`)
    ).status(),
  ).toBe(404);
  await readerPage.reload();
  await expect(taskRowLink(readerPage, { id: tasks[0].id })).toHaveCount(0);
  await reader.close();
  await owner.close();
});
