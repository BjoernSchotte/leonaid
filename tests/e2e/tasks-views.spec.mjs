import { test, expect } from "@playwright/test";
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

test("S3 server views paginate, group and retain navigation state on web and PWA", async ({
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
  await page.goto(
    `${baseURL}/admin/tasks/${list.id}?scope=all&view=due-today&sort=due&search=S3`,
  );

  const view = page.locator(".tasks-filter-status select");
  const sort = page.locator(".tasks-filter-sort select");
  await expect(view).toHaveValue("due-today");
  await expect(sort).toHaveValue("due");
  await expect(
    page.getByRole("button", {
      name: "S3 Heute hinter Seite eins",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: "S3 Heute und zurückgestellt",
      exact: true,
    }),
  ).toBeVisible();
  await expect.poll(() => taskQueries.length).toBeGreaterThan(0);
  const todayQuery = taskQueries.at(-1).searchParams;
  expect(todayQuery.get("deferredState")).toBe("all");
  expect(todayQuery.get("sort")).toBe("due");
  expect(todayQuery.get("dueFrom")).toBeTruthy();
  expect(todayQuery.get("dueBefore")).toBeTruthy();

  await view.selectOption("deferred");
  await expect(page).toHaveURL(/view=deferred/);
  await expect(
    page.getByRole("button", {
      name: "S3 Heute und zurückgestellt",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: "S3 Heute hinter Seite eins",
      exact: true,
    }),
  ).toHaveCount(0);

  await view.selectOption("open");
  await sort.selectOption("section");
  await expect(page).toHaveURL(/sort=section/);
  const more = page.getByRole("button", { name: "Weitere Aufgaben" });
  await more.click();
  await expect(page.locator(".task-row")).toHaveCount(100);
  await more.click();
  await expect(page.locator(".task-row")).toHaveCount(121);
  await expect(more).toHaveCount(0);
  await expect(
    page.locator(".task-section-heading h2", { hasText: "Planung" }),
  ).toHaveCount(1);
  await expect(
    page.locator(".task-section-heading h2", { hasText: "Umsetzung" }),
  ).toHaveCount(1);
  await expect(
    page.locator(".task-section-heading h2", { hasText: "Ohne Abschnitt" }),
  ).toHaveCount(1);
  await page.locator(".task-section-heading").first().scrollIntoViewIfNeeded();
  await page.screenshot({
    path: testInfo.outputPath("s3-desktop-sections.png"),
    fullPage: false,
  });

  await view.selectOption("due-next");
  await expect(
    page.getByRole("button", { name: "S3 Morgen", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".task-row")).toHaveCount(1);
  const filteredUrl = page.url();
  await page.getByRole("button", { name: "S3 Morgen", exact: true }).click();
  await expect(page).toHaveURL(/task=/);
  await page.goBack();
  await expect(page).toHaveURL(filteredUrl);
  await expect(page.locator(".tasks-filter-status select")).toHaveValue(
    "due-next",
  );

  const mobile = await signedInContext(browser, 390);
  const mobilePage = await mobile.newPage();
  await mobilePage.goto(
    `${baseURL}/app/tasks/${list.id}?scope=all&view=due-today&sort=due&search=S3`,
  );
  await expect(mobilePage.locator(".tasks-filter-status select")).toHaveValue(
    "due-today",
  );
  await expect(
    mobilePage.getByRole("button", {
      name: "S3 Heute und zurückgestellt",
      exact: true,
    }),
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
