// Fixture for the manual-ordering journeys: a shared list with two sections
// and twelve tasks, all planned for tomorrow by the owner and the reader.
import { expect } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";

const fixture = JSON.parse(
  readFileSync(process.env.LEONAID_MODULE_FIXTURE, "utf8"),
);
export const baseURL = process.env.LEONAID_E2E_BASE_URL;

export async function signedInContext(browser, session, options) {
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

export async function createFixture(owner, reader) {
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
  // Without a reader context nobody plans the tasks, so journeys that count
  // plans do not see another journey's twelve.
  for (const context of reader ? [owner, reader] : []) {
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
