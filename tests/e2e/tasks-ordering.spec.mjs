import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";

const fixture = JSON.parse(
  readFileSync(process.env.LEONAID_MODULE_FIXTURE, "utf8"),
);
const baseURL = process.env.LEONAID_E2E_BASE_URL;

async function signedInContext(browser, session, options) {
  const context = await browser.newContext({
    viewport: { width: options.width, height: 844 },
    hasTouch: options.touch ?? false,
    isMobile: options.touch ?? false,
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

function tomorrow() {
  const current = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Europe/Berlin",
  }).format(new Date());
  const value = new Date(`${current}T12:00:00Z`);
  value.setUTCDate(value.getUTCDate() + 1);
  return value.toISOString().slice(0, 10);
}

async function createFixture(owner, reader) {
  const headers = { Origin: baseURL };
  const listResponse = await owner.request.post(
    `${baseURL}/api/v1/task-lists`,
    {
      headers,
      data: {
        title: `S6 Manuelle Reihenfolge ${randomUUID()}`,
        actionId: null,
        idempotencyKey: randomUUID(),
      },
    },
  );
  expect(listResponse.ok()).toBe(true);
  let list = await listResponse.json();
  const grant = await owner.request.put(
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
  const epics = [];
  for (const title of ["S6 Vorbereitung", "S6 Leerer Abschnitt"]) {
    const response = await owner.request.post(
      `${baseURL}/api/v1/task-lists/${list.id}/epics`,
      { headers, data: { title, idempotencyKey: randomUUID() } },
    );
    expect(response.ok()).toBe(true);
    epics.push(await response.json());
  }
  const tasks = [];
  for (let index = 0; index < 12; index++) {
    const response = await owner.request.post(
      `${baseURL}/api/v1/task-lists/${list.id}/tasks`,
      {
        headers,
        data: {
          title: `S6 Aufgabe ${String(index + 1).padStart(2, "0")}`,
          description: "Reihenfolgenachweis",
          epicId: epics[0].id,
          assigneeUserId: null,
          dueAt: null,
          deferredUntil: null,
          idempotencyKey: randomUUID(),
        },
      },
    );
    expect(response.ok()).toBe(true);
    tasks.push(await response.json());
  }
  const plannedOn = tomorrow();
  for (const context of [owner, reader]) {
    for (const task of tasks) {
      const response = await context.request.put(
        `${baseURL}/api/v1/tasks/${task.id}/plan`,
        {
          headers,
          data: {
            state: "scheduled",
            plannedOn,
            expectedRevision: 0,
            idempotencyKey: randomUUID(),
          },
        },
      );
      expect(response.ok()).toBe(true);
    }
  }
  return { list, epics, tasks, plannedOn };
}

async function rowTitles(page) {
  return page.locator(".task-row .task-title-text").allTextContents();
}

async function mouseDrag(page, source, target) {
  await source.scrollIntoViewIfNeeded();
  await target.scrollIntoViewIfNeeded();
  const from = await source.boundingBox();
  const to = await target.boundingBox();
  expect(from).not.toBeNull();
  expect(to).not.toBeNull();
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2 + 8, {
    steps: 2,
  });
  await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, {
    steps: 12,
  });
  await page.mouse.up();
}

async function touchDrag(context, page, source, target) {
  await source.scrollIntoViewIfNeeded();
  await target.scrollIntoViewIfNeeded();
  const from = await source.boundingBox();
  const to = await target.boundingBox();
  expect(from).not.toBeNull();
  expect(to).not.toBeNull();
  const session = await context.newCDPSession(page);
  const point = (box) => ({
    x: box.x + box.width / 2,
    y: box.y + box.height / 2,
  });
  await session.send("Input.dispatchTouchEvent", {
    type: "touchStart",
    touchPoints: [point(from)],
  });
  await page.waitForTimeout(260);
  await session.send("Input.dispatchTouchEvent", {
    type: "touchMove",
    touchPoints: [point(to)],
  });
  await page.waitForTimeout(80);
  await session.send("Input.dispatchTouchEvent", {
    type: "touchEnd",
    touchPoints: [],
  });
  await session.detach();
}

test("S6 manual ordering persists across pointer, keyboard, menu and touch", async ({
  browser,
}, testInfo) => {
  const owner = await signedInContext(browser, 0, { width: 1440 });
  const reader = await signedInContext(browser, 1, { width: 390, touch: true });
  const { list, epics, tasks, plannedOn } = await createFixture(owner, reader);

  const desktop = await owner.newPage();
  await desktop.goto(
    `${baseURL}/admin/tasks/${list.id}?scope=all&view=open&sort=created`,
  );
  await expect(desktop.locator(".task-order-handle")).toHaveCount(0);
  await desktop.getByLabel("Sortierung").selectOption("manual");
  await expect(desktop.locator(".task-order-handle")).toHaveCount(12);

  const pointerResponse = desktop.waitForResponse(
    (response) =>
      response.request().method() === "PATCH" &&
      response.url().endsWith(`/api/v1/tasks/${tasks[2].id}/position`),
  );
  await mouseDrag(
    desktop,
    desktop.getByRole("button", {
      name: `Aufgabe verschieben: ${tasks[2].title}`,
    }),
    desktop.getByRole("button", {
      name: `Aufgabe verschieben: ${tasks[0].title}`,
    }),
  );
  expect((await pointerResponse).ok()).toBe(true);
  await expect
    .poll(() => rowTitles(desktop))
    .toEqual([
      tasks[2].title,
      tasks[0].title,
      tasks[1].title,
      ...tasks.slice(3).map((task) => task.title),
    ]);

  const keyboardHandle = desktop.getByRole("button", {
    name: `Aufgabe verschieben: ${tasks[2].title}`,
  });
  await keyboardHandle.focus();
  const keyboardResponse = desktop.waitForResponse(
    (response) =>
      response.request().method() === "PATCH" &&
      response.url().endsWith(`/api/v1/tasks/${tasks[2].id}/position`),
  );
  await desktop.keyboard.press("Space");
  await desktop.waitForTimeout(50);
  await desktop.keyboard.press("ArrowDown");
  await desktop.waitForTimeout(100);
  await desktop.keyboard.press("Space");
  expect((await keyboardResponse).ok()).toBe(true);
  await expect(keyboardHandle).toBeFocused();
  await expect
    .poll(() => rowTitles(desktop))
    .toEqual([
      tasks[0].title,
      tasks[2].title,
      tasks[1].title,
      ...tasks.slice(3).map((task) => task.title),
    ]);

  const fourthRow = desktop.locator(`[data-task-id="${tasks[3].id}"]`);
  const fourthMenu = fourthRow.locator("summary");
  await expect(fourthMenu).toHaveAttribute(
    "aria-label",
    `Aktionen für ${tasks[3].title}`,
  );
  await fourthMenu.click();
  const menuResponse = desktop.waitForResponse(
    (response) =>
      response.request().method() === "PATCH" &&
      response.url().endsWith(`/api/v1/tasks/${tasks[3].id}/position`),
  );
  await fourthRow.getByRole("button", { name: "Nach oben" }).click();
  expect((await menuResponse).ok()).toBe(true);
  await expect
    .poll(() => rowTitles(desktop))
    .toEqual([
      tasks[0].title,
      tasks[2].title,
      tasks[3].title,
      tasks[1].title,
      ...tasks.slice(4).map((task) => task.title),
    ]);

  const secondRow = desktop.locator(`[data-task-id="${tasks[1].id}"]`);
  const secondMenu = secondRow.locator("summary");
  await expect(secondMenu).toHaveAttribute(
    "aria-label",
    `Aktionen für ${tasks[1].title}`,
  );
  await secondMenu.click();
  await secondRow.getByLabel("In Abschnitt").selectOption(epics[1].id);
  const sectionResponse = desktop.waitForResponse(
    (response) =>
      response.request().method() === "PATCH" &&
      response.url().endsWith(`/api/v1/tasks/${tasks[1].id}/position`),
  );
  await secondRow
    .getByRole("button", { name: "Verschieben", exact: true })
    .click();
  expect((await sectionResponse).ok()).toBe(true);
  await expect(
    desktop.getByRole("heading", { name: epics[1].title, exact: true }),
  ).toBeVisible();
  await desktop.reload();
  await expect(
    desktop.locator(`[data-task-id="${tasks[1].id}"]`),
  ).toContainText(epics[1].title);
  await desktop.screenshot({
    path: testInfo.outputPath("s6-desktop-manual-order.png"),
    fullPage: false,
  });

  const mobile = await reader.newPage();
  await mobile.goto(
    `${baseURL}/app/tasks/${list.id}?scope=all&view=open&sort=manual`,
  );
  await expect(mobile.locator(".task-order-handle")).toHaveCount(0);
  await mobile.goto(`${baseURL}/app/tasks?scope=mine&view=plan-planned`);
  await expect(mobile.locator(".task-order-handle")).toHaveCount(12);
  await expect(mobile.locator(".task-complete")).toHaveCount(0);
  expect(
    await mobile
      .locator(".task-title")
      .first()
      .evaluate((element) => getComputedStyle(element).touchAction),
  ).not.toBe("none");
  expect(
    await mobile
      .locator(".task-order-handle")
      .first()
      .evaluate((element) => getComputedStyle(element).touchAction),
  ).toBe("none");

  const touchResponse = mobile.waitForResponse(
    (response) =>
      response.request().method() === "PATCH" &&
      response.url().endsWith(`/api/v1/tasks/${tasks[2].id}/position`),
  );
  await touchDrag(
    reader,
    mobile,
    mobile.getByRole("button", {
      name: `Aufgabe verschieben: ${tasks[2].title}`,
    }),
    mobile.getByRole("button", {
      name: `Aufgabe verschieben: ${tasks[0].title}`,
    }),
  );
  const touchResult = await touchResponse;
  expect(touchResult.ok(), await touchResult.text()).toBe(true);
  await expect
    .poll(() => rowTitles(mobile))
    .toEqual([
      tasks[2].title,
      tasks[0].title,
      tasks[1].title,
      ...tasks.slice(3).map((task) => task.title),
    ]);

  const planRow = mobile.locator(`[data-task-id="${tasks[2].id}"]`);
  const planMenu = planRow.locator("summary");
  await expect(planMenu).toHaveAttribute(
    "aria-label",
    `Aktionen für ${tasks[2].title}`,
  );
  await planMenu.click();
  const nextDate = new Date(`${plannedOn}T12:00:00Z`);
  nextDate.setUTCDate(nextDate.getUTCDate() + 1);
  const nextDateValue = nextDate.toISOString().slice(0, 10);
  await planRow.getByLabel("Für Tag planen").fill(nextDateValue);
  const dateResponse = mobile.waitForResponse(
    (response) =>
      response.request().method() === "PATCH" &&
      response.url().endsWith(`/api/v1/tasks/${tasks[2].id}/position`),
  );
  await planRow.getByRole("button", { name: "Planen" }).click();
  expect((await dateResponse).ok()).toBe(true);
  await expect(planRow).toContainText(
    new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(nextDate),
  );
  expect(
    await mobile.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await mobile.screenshot({
    path: testInfo.outputPath("s6-pwa-touch-order.png"),
    fullPage: false,
  });

  const ownerPlan = await owner.request.get(
    `${baseURL}/api/v1/task-plans?view=planned&timeZone=Europe%2FBerlin&limit=50`,
  );
  expect(ownerPlan.ok()).toBe(true);
  expect(
    (await ownerPlan.json()).items.slice(0, 3).map((task) => task.id),
  ).toEqual(tasks.slice(0, 3).map((task) => task.id));
  await reader.close();
  await owner.close();
});
