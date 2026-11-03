// Keyboard walk through the task list: j/k, Enter, Esc, x, the property
// letters (s, w, a, p), c for the quick add, f for filters, and the palette.
import { test, expect } from "./csp-guard.mjs";
import AxeBuilder from "@axe-core/playwright";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import {
  pickOption,
  rowTitles,
  taskPane,
  taskRow,
  taskRowLink,
  taskRows,
} from "./task-list.mjs";

const fixture = JSON.parse(
  readFileSync(process.env.LEONAID_MODULE_FIXTURE, "utf8"),
);
const baseURL = process.env.LEONAID_E2E_BASE_URL;

async function signedInContext(browser, width) {
  const context = await browser.newContext({
    viewport: { width, height: 900 },
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

async function createList(context) {
  const headers = { Origin: baseURL };
  const listResponse = await context.request.post(
    `${baseURL}/api/v1/task-lists`,
    {
      headers,
      data: {
        title: `Tastatur ${randomUUID()}`,
        actionId: null,
        idempotencyKey: randomUUID(),
      },
    },
  );
  expect(listResponse.ok()).toBe(true);
  const list = await listResponse.json();
  const tasks = [];
  for (const title of ["T1 Stände", "T2 Kasse", "T3 Plakate"]) {
    const response = await context.request.post(
      `${baseURL}/api/v1/task-lists/${list.id}/tasks`,
      {
        headers,
        data: {
          title,
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
    tasks.push(await response.json());
  }
  return { list, tasks };
}

async function expectNoSeriousViolations(page, label) {
  const results = await new AxeBuilder({ page }).include(".listview").analyze();
  const serious = results.violations.filter((violation) =>
    ["serious", "critical"].includes(violation.impact),
  );
  expect(serious, `${label}: ${JSON.stringify(serious, null, 2)}`).toEqual([]);
}

test("task list: j/k, Enter, Esc, x, property keys, quick add, filter and palette", async ({
  browser,
}) => {
  const context = await signedInContext(browser, 1440);
  const { list, tasks } = await createList(context);
  const identity = await (
    await context.request.get(`${baseURL}/api/v1/identity/me`)
  ).json();
  const page = await context.newPage();
  await page.goto(`${baseURL}/admin/tasks/${list.id}`);
  await expect(taskRows(page)).toHaveCount(3);
  expect(await rowTitles(page)).toEqual(tasks.map((task) => task.title));
  await expectNoSeriousViolations(page, "list");

  // j/k move the focus ring over the rows.
  await page.keyboard.press("j");
  await expect(taskRowLink(page, { id: tasks[0].id })).toBeFocused();
  await page.keyboard.press("j");
  await page.keyboard.press("j");
  await page.keyboard.press("k");
  await expect(taskRowLink(page, { id: tasks[1].id })).toBeFocused();

  // Enter opens the pane, j moves it along, Esc closes it again.
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`open=${tasks[1].id}`));
  await expect(taskPane(page, tasks[1].id)).toBeVisible();
  await expectNoSeriousViolations(page, "pane");
  await page.keyboard.press("j");
  await expect(taskPane(page, tasks[2].id)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(taskPane(page)).toHaveCount(0);
  await expect(taskRowLink(page, { id: tasks[2].id })).toBeFocused();

  // x checks rows; the bulk bar acts on them; Esc clears the selection.
  await page.keyboard.press("x");
  await page.keyboard.press("k");
  await page.keyboard.press("x");
  const bulk = page.getByRole("region", { name: "Auswahl" });
  await expect(bulk).toContainText("2 ausgewählt");
  await expectNoSeriousViolations(page, "bulk bar");
  // p on a checked row sets the priority of both.
  await page.keyboard.press("p");
  await pickOption(page, "Hoch");
  await expect(
    page.getByText("Priorität bei 2 Einträgen: Hoch", { exact: true }),
  ).toBeVisible();
  for (const task of tasks.slice(1)) {
    await expect(
      taskRow(page, task.id).locator('.flag-high[aria-label="Hohe Priorität"]'),
    ).toBeVisible();
  }
  await page.keyboard.press("Escape");
  await expect(bulk).toHaveCount(0);

  // a assigns the focused row; w plans it for today in my plan.
  await page.keyboard.press("a");
  await pickOption(page, `${identity.displayName} (ich)`);
  await expect(
    taskRow(page, tasks[1].id).locator(
      `.avatar[aria-label="Zuständig: ${identity.displayName}"]`,
    ),
  ).toBeVisible();
  await expect(taskRow(page, tasks[1].id)).not.toHaveAttribute(
    "aria-busy",
    "true",
  );
  await page.keyboard.press("w");
  await pickOption(page, "Heute");
  await expect(taskRow(page, tasks[1].id).locator(".task-plan")).toHaveText(
    "Heute",
  );
  // The saved edit (and its refresh) has settled before the next one.
  await expect(taskRow(page, tasks[1].id)).not.toHaveAttribute(
    "aria-busy",
    "true",
  );
  // s marks it done: "Offen" drops it, Rückgängig brings it back.
  await page.keyboard.press("s");
  await pickOption(page, "Erledigt");
  await expect(taskRow(page, tasks[1].id)).toHaveCount(0);
  await page
    .locator(".toast", { hasText: "Status: Erledigt" })
    .getByRole("button", { name: "Rückgängig", exact: true })
    .click();
  await expect(taskRow(page, tasks[1].id)).toBeVisible();

  // f adds a filter; the URL carries it.
  await page.keyboard.press("f");
  const popover = page.locator(".popover");
  await popover.getByRole("option", { name: "Priorität", exact: true }).click();
  await popover.getByRole("option", { name: "Hoch", exact: true }).click();
  await page.keyboard.press("Escape");
  await expect(page).toHaveURL(/f\.priority=high/);
  await expect(taskRows(page)).toHaveCount(2);
  await expectNoSeriousViolations(page, "filtered");
  await page.getByRole("button", { name: "Zurücksetzen" }).click();
  await expect(taskRows(page)).toHaveCount(3);

  // c opens the quick add; Enter creates, Esc closes, typing is inert.
  await page.evaluate(() => document.activeElement?.blur());
  await page.keyboard.press("c");
  const quick = page.getByRole("form", { name: "Aufgabe schnell erfassen" });
  const field = quick.getByLabel("Titel", { exact: true });
  await expect(field).toBeFocused();
  await field.pressSequentially("jx Neue Tastaturaufgabe");
  await expect(taskPane(page)).toHaveCount(0);
  await field.press("Enter");
  await expect(
    taskRowLink(page, { title: "jx Neue Tastaturaufgabe" }),
  ).toBeVisible();
  await field.press("Escape");
  await expect(quick).toHaveCount(0);

  // The palette offers the list's views and the create command.
  await page.keyboard.press("Control+k");
  const palette = page.getByRole("dialog", { name: "Befehlspalette" });
  await expect(palette.getByRole("combobox")).toBeFocused();
  await page.keyboard.type("Ansicht: Erledigt");
  await page.keyboard.press("Enter");
  await expect(palette).toBeHidden();
  await expect(
    page
      .getByRole("navigation", { name: "Gespeicherte Ansichten" })
      .getByRole("button", { name: "Erledigt", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(page).toHaveURL(/view=done/);

  // The help overlay lists the list keys.
  await page.evaluate(() => document.activeElement?.blur());
  await page.keyboard.press("?");
  const help = page.getByRole("dialog", { name: /Tastenkürzel/ });
  await expect(help).toBeVisible();
  for (const label of [
    "Nächste Zeile",
    "Zeile öffnen",
    "Zeile auswählen",
    "Status ändern",
    "Plan ändern",
    "Zuständig ändern",
    "Priorität ändern",
    "Aufgabe anlegen",
  ]) {
    await expect(help.getByText(label, { exact: true })).toBeVisible();
  }
  await page.keyboard.press("Escape");
  await context.close();
});
