// Holds one real reorder request until the test releases it, then forwards it
// unchanged: the grip or pane button that started the move must keep focus
// while the move saves and after the list re-sorts. Every response comes
// from the real API.
import { expect, test } from "./csp-guard.mjs";
import { openTask, rowTitles } from "./task-list.mjs";
import {
  baseURL,
  createFixture,
  signedInContext,
} from "./task-ordering-fixture.mjs";

/**
 * Holds the next PATCH to the task's position until `release()`, then
 * forwards it unchanged. Later requests pass straight through.
 */
async function holdMove(page, taskId) {
  let release;
  const released = new Promise((done) => {
    release = done;
  });
  let arrived;
  const held = new Promise((done) => {
    arrived = done;
  });
  let holding = true;
  const pattern = `**/api/v1/tasks/${taskId}/position`;
  const handler = async (route) => {
    if (!holding || route.request().method() !== "PATCH") {
      await route.continue();
      return;
    }
    holding = false;
    arrived();
    await released;
    await route.continue();
  };
  await page.route(pattern, handler);
  const answered = page.waitForResponse(
    (candidate) =>
      candidate.request().method() === "PATCH" &&
      candidate.url().endsWith(`/api/v1/tasks/${taskId}/position`),
  );
  const response = answered.then(async (result) => {
    await page.unroute(pattern, handler);
    return result;
  });
  return { held, release: () => release(), response };
}

/** Counts the PATCH requests to the task's position from now on. */
function countMoves(page, taskId) {
  const counter = { count: 0 };
  page.on("request", (request) => {
    if (
      request.method() === "PATCH" &&
      request.url().endsWith(`/api/v1/tasks/${taskId}/position`)
    ) {
      counter.count += 1;
    }
  });
  return counter;
}

/** Picks up the focused grip, moves it one row down (or up) and drops it. */
async function keyboardMove(page, key = "ArrowDown") {
  await page.keyboard.press("Space");
  await page.waitForTimeout(50);
  await page.keyboard.press(key);
  await page.waitForTimeout(100);
  await page.keyboard.press("Space");
}

function gripOf(page, task) {
  return page.getByRole("button", {
    name: `Aufgabe verschieben: ${task.title}`,
  });
}

test("S6 a held reorder keeps focus on the grip and the pane button", async ({
  browser,
}) => {
  const owner = await signedInContext(browser, 0, { width: 1440 });
  // No plans: the S6 journey counts the plans of both users.
  const { list, epics, tasks } = await createFixture(owner, null);

  const page = await owner.newPage();
  await page.goto(`${baseURL}/admin/tasks/${list.id}?sort=created`);
  await page.getByLabel("Sortieren").selectOption("manual");
  await expect(page.locator(".task-order-handle")).toHaveCount(12);
  const titles = tasks.map((task) => task.title);
  await expect.poll(() => rowTitles(page)).toEqual(titles);

  // Keyboard: pick up the first grip, move it one down, drop it.
  const grip = gripOf(page, tasks[0]);
  const keyboardMove = await holdMove(page, tasks[0].id);
  const gripRequests = countMoves(page, tasks[0].id);
  await grip.focus();
  await keyboardMove(page);
  await keyboardMove.held;
  // While it saves the grip is inert but still focusable and focused.
  await expect(grip).toHaveAttribute("aria-disabled", "true");
  // Not the HTML attribute: that would drop focus to <body>.
  expect(await grip.evaluate((element) => element.disabled)).toBe(false);
  await expect(grip).toBeFocused();
  // Inert while saving: a second pick-up and move starts no drag and sends
  // nothing.
  await keyboardMove(page);
  await expect(grip).not.toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".tasks-page .row[data-dragging]")).toHaveCount(0);
  await expect(grip).toBeFocused();
  keyboardMove.release();
  expect((await keyboardMove.response).ok()).toBe(true);
  await expect
    .poll(() => rowTitles(page))
    .toEqual([titles[1], titles[0], ...titles.slice(2)]);
  await expect(grip).toHaveAttribute("aria-disabled", "false");
  await expect(grip).toBeFocused();
  expect(gripRequests.count).toBe(1);

  // Pane: "Nach oben" by keyboard keeps its focus while the move saves.
  const pane = await openTask(page, { id: tasks[3].id });
  const up = pane.getByRole("button", { name: "Nach oben" });
  const paneMove = await holdMove(page, tasks[3].id);
  const paneRequests = countMoves(page, tasks[3].id);
  await up.focus();
  await page.keyboard.press("Enter");
  await paneMove.held;
  await expect(up).toHaveAttribute("aria-disabled", "true");
  expect(await up.evaluate((element) => element.disabled)).toBe(false);
  await expect(up).toBeFocused();
  // Inert while saving: a second press sends nothing.
  await page.keyboard.press("Enter");
  paneMove.release();
  expect((await paneMove.response).ok()).toBe(true);
  const afterPane = [
    titles[1],
    titles[0],
    titles[3],
    titles[2],
    ...titles.slice(4),
  ];
  await expect.poll(() => rowTitles(page)).toEqual(afterPane);
  await expect(up).not.toHaveAttribute("aria-disabled", "true");
  await expect(up).toBeFocused();
  expect(paneRequests.count).toBe(1);

  // Into another section: the row leaves its group and is mounted anew
  // under the other section header; focus must follow it to the new grip.
  await page.keyboard.press("Escape");
  const last = await openTask(page, { id: tasks[11].id });
  await last.getByLabel("In Abschnitt").selectOption(epics[1].id);
  const sectionResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "PATCH" &&
      response.url().endsWith(`/api/v1/tasks/${tasks[11].id}/position`),
  );
  await last.getByRole("button", { name: "Verschieben", exact: true }).click();
  expect((await sectionResponse).ok()).toBe(true);
  await page.keyboard.press("Escape");
  const section = page.locator(".group-header", { hasText: epics[1].title });
  await expect(section).toBeVisible();
  // The section order decides on which side of the boundary its one task
  // sits; the neighbouring row across the boundary crosses into it.
  const before = await rowTitles(page);
  const lonely = before.indexOf(titles[11]);
  expect([0, before.length - 1]).toContain(lonely);
  const first = lonely === 0;
  const neighbour = before[first ? 1 : lonely - 1];
  const mover = tasks[titles.indexOf(neighbour)];
  const crossing = gripOf(page, mover);
  const oldGrip = await crossing.elementHandle();
  const crossMove = await holdMove(page, mover.id);
  await crossing.focus();
  await keyboardMove(page, first ? "ArrowUp" : "ArrowDown");
  await crossMove.held;
  await expect(crossing).toBeFocused();
  crossMove.release();
  expect((await crossMove.response).ok()).toBe(true);
  const rest = before.filter(
    (title) => title !== titles[11] && title !== neighbour,
  );
  await expect
    .poll(() => rowTitles(page))
    .toEqual(
      first
        ? [neighbour, titles[11], ...rest]
        : [...rest, titles[11], neighbour],
    );
  // The grip now sits in the other section, as a newly mounted element.
  expect(await oldGrip.evaluate((element) => element.isConnected)).toBe(false);
  await expect(crossing).toBeFocused();
  await owner.close();
});
