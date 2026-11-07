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

test("S6 a held reorder keeps focus on the grip and the pane button", async ({
  browser,
}) => {
  const owner = await signedInContext(browser, 0, { width: 1440 });
  // No plans: the S6 journey counts the plans of both users.
  const { list, tasks } = await createFixture(owner, null);

  const page = await owner.newPage();
  await page.goto(`${baseURL}/admin/tasks/${list.id}?sort=created`);
  await page.getByLabel("Sortieren").selectOption("manual");
  await expect(page.locator(".task-order-handle")).toHaveCount(12);
  const titles = tasks.map((task) => task.title);
  await expect.poll(() => rowTitles(page)).toEqual(titles);

  // Keyboard: pick up the first grip, move it one down, drop it.
  const grip = page.getByRole("button", {
    name: `Aufgabe verschieben: ${tasks[0].title}`,
  });
  const keyboardMove = await holdMove(page, tasks[0].id);
  await grip.focus();
  await page.keyboard.press("Space");
  await page.waitForTimeout(50);
  await page.keyboard.press("ArrowDown");
  await page.waitForTimeout(100);
  await page.keyboard.press("Space");
  await keyboardMove.held;
  // While it saves the grip is inert but still focusable and focused.
  await expect(grip).toHaveAttribute("aria-disabled", "true");
  // Not the HTML attribute: that would drop focus to <body>.
  expect(await grip.evaluate((element) => element.disabled)).toBe(false);
  await expect(grip).toBeFocused();
  keyboardMove.release();
  expect((await keyboardMove.response).ok()).toBe(true);
  await expect
    .poll(() => rowTitles(page))
    .toEqual([titles[1], titles[0], ...titles.slice(2)]);
  await expect(grip).toHaveAttribute("aria-disabled", "false");
  await expect(grip).toBeFocused();

  // Pane: "Nach oben" by keyboard keeps its focus while the move saves.
  const pane = await openTask(page, { id: tasks[3].id });
  const up = pane.getByRole("button", { name: "Nach oben" });
  const paneMove = await holdMove(page, tasks[3].id);
  let paneRequests = 0;
  page.on("request", (request) => {
    if (
      request.method() === "PATCH" &&
      request.url().endsWith(`/api/v1/tasks/${tasks[3].id}/position`)
    ) {
      paneRequests += 1;
    }
  });
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
  await expect
    .poll(() => rowTitles(page))
    .toEqual([titles[1], titles[0], titles[3], titles[2], ...titles.slice(4)]);
  await expect(up).not.toHaveAttribute("aria-disabled", "true");
  await expect(up).toBeFocused();
  expect(paneRequests).toBe(1);
  await owner.close();
});
