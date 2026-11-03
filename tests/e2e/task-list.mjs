// Helpers for the task list (ListView rows and the detail pane or sheet).
import { expect } from "@playwright/test";

/** Every visible task row. */
export function taskRows(page) {
  return page.locator(".listview .row");
}

/** The whole row of one task (grip, chips, plan), by task id. */
export function taskRow(page, id) {
  return page.locator(`.listview .row:has([data-task-row="${id}"])`);
}

/** The row link of one task, by id or by its exact title. */
export function taskRowLink(page, { id, title }) {
  if (id) {
    return page.locator(".listview .row-link", {
      has: page.locator(`[data-task-row="${id}"]`),
    });
  }
  return page.locator(".listview .row-link", {
    has: page.locator("[data-task-row]").getByText(title, { exact: true }),
  });
}

/** Titles of the visible rows, top to bottom. */
export function rowTitles(page) {
  return page.locator(".listview .row [data-task-row]").allTextContents();
}

/** The pane (desktop) or sheet (phone) body of the open task. */
export function taskPane(page, id) {
  return id
    ? page.locator(`[data-testid="task-detail"][data-task-id="${id}"]`)
    : page.getByTestId("task-detail");
}

/** Opens one task and returns its pane. */
export async function openTask(page, row) {
  await taskRowLink(page, row).click();
  const pane = row.id
    ? taskPane(page, row.id)
    : page
        .getByTestId("task-detail")
        .filter({ has: page.locator("form, section") });
  await expect(pane).toBeVisible();
  return pane;
}

/** Switches the list to a built-in view tab ("Offen", "Erledigt", …). */
export async function showTaskView(page, label) {
  const tab = page
    .getByRole("navigation", { name: "Gespeicherte Ansichten" })
    .getByRole("button", { name: label, exact: true });
  await tab.click();
  await expect(tab).toHaveAttribute("aria-pressed", "true");
}

/** The search field of the list. */
export function taskSearch(page) {
  return page.getByRole("searchbox");
}

/** Picks an option in the open option menu (status, assignee, …). */
export async function pickOption(page, name) {
  await page
    .locator(".popover")
    .getByRole("option", { name, exact: true })
    .click();
}

/**
 * Elements that stick out of the viewport on the right (not inside a
 * horizontally scrolling or clipping box): empty when the page fits.
 */
export function horizontalOverflow(page) {
  return page.evaluate(() => {
    const width = document.documentElement.clientWidth;
    const clipped = (element) => {
      for (let node = element.parentElement; node; node = node.parentElement) {
        const style = getComputedStyle(node);
        if (
          style.overflowX !== "visible" &&
          node !== document.body &&
          node !== document.documentElement
        )
          return true;
      }
      return false;
    };
    return [...document.querySelectorAll("body *")]
      .filter((element) => {
        const box = element.getBoundingClientRect();
        return box.width > 0 && box.right > width + 1 && !clipped(element);
      })
      .slice(0, 8)
      .map(
        (element) =>
          `${element.tagName.toLowerCase()}.${[...element.classList].join(".")} right=${Math.round(element.getBoundingClientRect().right)}`,
      );
  });
}
