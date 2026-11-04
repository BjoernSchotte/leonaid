import { test, expect } from "./csp-guard.mjs";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { taskRowLink, taskRows } from "./task-list.mjs";

const fixture = JSON.parse(
  readFileSync(process.env.LEONAID_MODULE_FIXTURE, "utf8"),
);
const baseURL = process.env.LEONAID_E2E_BASE_URL;

async function signedInContext(browser, width) {
  const context = await browser.newContext({
    viewport: { width, height: 844 },
    ignoreHTTPSErrors: true,
    timezoneId: "Europe/Berlin",
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

async function createViewsFixture(context, times) {
  const headers = { Origin: baseURL };
  const listResponse = await context.request.post(
    `${baseURL}/api/v1/task-lists`,
    {
      headers,
      data: {
        title: `S3 Terminansichten ${randomUUID()}`,
        actionId: null,
        idempotencyKey: randomUUID(),
      },
    },
  );
  expect(listResponse.ok()).toBe(true);
  const list = await listResponse.json();
  const epics = [];
  for (const title of ["Planung", "Umsetzung"]) {
    const response = await context.request.post(
      `${baseURL}/api/v1/task-lists/${list.id}/epics`,
      { headers, data: { title, idempotencyKey: randomUUID() } },
    );
    expect(response.ok()).toBe(true);
    epics.push(await response.json());
  }
  const definitions = Array.from({ length: 122 }, (_, index) => ({
    title:
      index === 75
        ? "S3 Heute hinter Seite eins"
        : index === 76
          ? "S3 Heute und zurückgestellt"
          : index === 77
            ? "S3 Morgen"
            : `S3 Aufgabe ${String(index).padStart(3, "0")}`,
    dueAt:
      index === 75 || index === 76
        ? times.todayNoon
        : index === 77
          ? times.tomorrowNoon
          : null,
    deferredUntil: index === 76 ? times.tomorrowNoon : null,
    epicId:
      index % 3 === 0 ? epics[0].id : index % 3 === 1 ? epics[1].id : null,
  }));
  const created = [];
  for (let offset = 0; offset < definitions.length; offset += 10) {
    const batch = await Promise.all(
      definitions.slice(offset, offset + 10).map(async (definition) => {
        const response = await context.request.post(
          `${baseURL}/api/v1/task-lists/${list.id}/tasks`,
          {
            headers,
            data: {
              ...definition,
              description: "",
              assigneeUserId: null,
              idempotencyKey: randomUUID(),
            },
          },
        );
        expect(response.ok()).toBe(true);
        return response.json();
      }),
    );
    created.push(...batch);
  }
  return { list, created };
}

test("S3 views load every page, filter, group and keep navigation state on web and PWA", async ({
  browser,
}, testInfo) => {
  const desktop = await signedInContext(browser, 1440);
  const timePage = await desktop.newPage();
  const times = await timePage.evaluate(() => {
    const now = new Date();
    const todayNoon = new Date(
      now.getFullYear(),
      now.getMonth(),
      now.getDate(),
      12,
    );
    const tomorrowNoon = new Date(
      now.getFullYear(),
      now.getMonth(),
      now.getDate() + 1,
      12,
    );
    return {
      todayNoon: todayNoon.toISOString(),
      tomorrowNoon: tomorrowNoon.toISOString(),
    };
  });
  await timePage.close();
  const { list } = await createViewsFixture(desktop, times);
  const page = await desktop.newPage();
  const taskQueries = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname === "/api/v1/tasks") {
      taskQueries.push(url);
    }
  });
  // An old "Heute fällig" bookmark becomes the due filter of "Offen".
  await page.goto(
    `${baseURL}/admin/tasks/${list.id}?scope=all&view=due-today&sort=due&search=S3`,
  );
  await expect(page).toHaveURL(/f\.due=today/);
  await expect(page).toHaveURL(/q=S3/);
  await expect(page).not.toHaveURL(/scope=|search=/);
  const filters = page.getByRole("group", { name: "Aktive Filter" });
  await expect(filters).toContainText("Fällig");
  await expect(
    taskRowLink(page, { title: "S3 Heute hinter Seite eins" }),
  ).toBeVisible();
  await expect(
    taskRowLink(page, { title: "S3 Heute und zurückgestellt" }),
  ).toBeVisible();
  await expect(taskRows(page)).toHaveCount(2);
  // All open tasks of the list arrive in pages of 100, without a button.
  const listQueries = taskQueries.filter(
    (url) => url.searchParams.get("listId") === list.id,
  );
  expect(
    listQueries
      .slice(0, 2)
      .map((url) => [
        url.searchParams.get("status"),
        url.searchParams.get("deferredState"),
        url.searchParams.get("offset"),
        url.searchParams.get("limit"),
      ]),
  ).toEqual([
    ["open", "all", "0", "100"],
    ["open", "all", "100", "100"],
  ]);
  await expect(
    page.getByRole("button", { name: "Weitere Aufgaben laden" }),
  ).toHaveCount(0);

  await page.goto(`${baseURL}/admin/tasks/${list.id}?scope=all&view=deferred`);
  await expect(page).toHaveURL(/f\.deferral=deferred/);
  await expect(
    taskRowLink(page, { title: "S3 Heute und zurückgestellt" }),
  ).toBeVisible();
  await expect(
    taskRowLink(page, { title: "S3 Heute hinter Seite eins" }),
  ).toHaveCount(0);

  // "Offen": every active task, grouped by section.
  await page.goto(`${baseURL}/admin/tasks/${list.id}`);
  await expect(taskRows(page)).toHaveCount(121);
  for (const section of ["Planung", "Umsetzung", "Ohne Abschnitt"]) {
    await expect(
      page.locator(".group-header", { hasText: section }),
    ).toHaveCount(1);
  }
  await page.locator(".group-header").first().scrollIntoViewIfNeeded();
  await page.screenshot({
    path: testInfo.outputPath("s3-desktop-sections.png"),
    fullPage: false,
  });

  // Filter "Fällig: Nächste 7 Tage" through the filter menu.
  await page.keyboard.press("f");
  await page
    .locator(".popover")
    .getByRole("option", { name: "Fällig" })
    .click();
  await page
    .locator(".popover")
    .getByRole("option", { name: "Nächste 7 Tage" })
    .click();
  await page.keyboard.press("Escape");
  await expect(page).toHaveURL(/f\.due=week/);
  await expect(taskRowLink(page, { title: "S3 Morgen" })).toBeVisible();
  await expect(taskRows(page)).toHaveCount(1);
  const filteredUrl = page.url();
  await taskRowLink(page, { title: "S3 Morgen" }).click();
  await expect(page).toHaveURL(/open=/);
  await page.goBack();
  await expect(page).toHaveURL(filteredUrl);
  await expect(taskRows(page)).toHaveCount(1);

  const mobile = await signedInContext(browser, 390);
  const mobilePage = await mobile.newPage();
  await mobilePage.goto(
    `${baseURL}/app/tasks/${list.id}?scope=all&view=due-today&sort=due&search=S3`,
  );
  await expect(mobilePage).toHaveURL(/f\.due=today/);
  await expect(
    taskRowLink(mobilePage, { title: "S3 Heute und zurückgestellt" }),
  ).toBeVisible();
  expect(
    await mobilePage.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await mobilePage.screenshot({
    path: testInfo.outputPath("s3-pwa-today.png"),
    fullPage: false,
  });
  await mobile.close();
  await desktop.close();
});
