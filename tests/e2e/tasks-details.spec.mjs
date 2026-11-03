import { test, expect } from "./csp-guard.mjs";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import {
  openTask,
  taskPane,
  taskRow,
  taskRowLink,
  taskSearch,
} from "./task-list.mjs";

const fixture = JSON.parse(
  readFileSync(process.env.LEONAID_MODULE_FIXTURE, "utf8"),
);
const baseURL = process.env.LEONAID_E2E_BASE_URL;

async function createListAndTasks(context, count = 14) {
  const headers = { Origin: baseURL };
  const listResponse = await context.request.post(
    `${baseURL}/api/v1/task-lists`,
    {
      headers,
      data: {
        title: `S2 Fokusliste ${randomUUID()}`,
        actionId: null,
        idempotencyKey: randomUUID(),
      },
    },
  );
  expect(listResponse.ok()).toBe(true);
  const list = await listResponse.json();
  const tasks = [];
  for (let index = 0; index < count; index += 1) {
    const response = await context.request.post(
      `${baseURL}/api/v1/task-lists/${list.id}/tasks`,
      {
        headers,
        data: {
          title: `S2 Detail ${String(index + 1).padStart(2, "0")}`,
          description: `Beschreibung ${index + 1}`,
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

async function signedInContext(browser, width, sessionIndex = 0) {
  const context = await browser.newContext({
    viewport: { width, height: 844 },
    ignoreHTTPSErrors: true,
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: fixture.sessions[sessionIndex],
      url: baseURL,
      secure: true,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  return context;
}

test("S2 quick capture requires a visible editable list and keeps URL filters", async ({
  browser,
}) => {
  const context = await signedInContext(browser, 1440);
  const { list } = await createListAndTasks(context, 1);
  const page = await context.newPage();
  await page.goto(`${baseURL}/admin/tasks?view=open`);

  await page
    .getByRole("button", { name: /^Aufgabe anlegen/ })
    .first()
    .click();
  const quick = page.getByRole("form", { name: "Aufgabe schnell erfassen" });
  await expect(quick).toBeVisible();
  const field = quick.getByLabel("Titel", { exact: true });
  await expect(field).toBeFocused();
  let writes = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      /\/task-lists\/[^/]+\/tasks$/.test(request.url())
    )
      writes += 1;
  });
  await field.press("Enter");
  expect(writes).toBe(0);
  // Without a list nothing is sent; the person is told to pick one.
  await quick.getByLabel("Aufgabenliste").selectOption("");
  const title = `S2 Schnellerfassung ${randomUUID()}`;
  await field.fill(title);
  await field.press("Enter");
  await expect(
    page.getByText("Wählen Sie zuerst eine Liste.", { exact: true }),
  ).toBeVisible();
  await expect(quick.getByLabel("Aufgabenliste")).toBeFocused();
  expect(writes).toBe(0);
  await quick.getByLabel("Aufgabenliste").selectOption(list.id);
  await field.press("Enter");
  await expect.poll(() => writes).toBe(1);
  await expect(
    page.getByText(`Aufgabe „${title}“ angelegt.`, { exact: true }),
  ).toBeVisible();
  await expect(field).toHaveValue("");
  await expect(taskRowLink(page, { title })).toBeVisible();
  await expect(page).toHaveURL(/view=open/);

  await field.press("Escape");
  await taskSearch(page).fill(title);
  await expect
    .poll(() => new URL(page.url()).searchParams.get("q"))
    .toBe(title);
  await page.reload();
  await expect(taskSearch(page)).toHaveValue(title);
  await expect(taskRowLink(page, { title })).toBeVisible();
  await context.close();
});

for (const [surface, width] of [
  ["admin", 1440],
  ["admin", 1024],
  ["admin", 720],
  ["app", 390],
  ["app", 320],
]) {
  test(`${surface} ${width}px: S2 responsive details, compact list tools and guarded navigation`, async ({
    browser,
  }, testInfo) => {
    const context = await signedInContext(browser, width);
    const { list, tasks } = await createListAndTasks(context);
    const page = await context.newPage();
    // An old bookmark: its filters become list view parameters.
    await page.goto(
      `${baseURL}/${surface}/tasks/${list.id}?scope=all&view=open&search=Detail`,
    );
    await expect(page).toHaveURL(new RegExp(`/tasks/${list.id}\\?q=Detail$`));
    await expect(taskSearch(page)).toHaveValue("Detail");

    const switcher = page.getByRole("button", { name: "Liste wechseln" });
    const access = page.getByRole("button", { name: "Zugriff verwalten" });
    await expect(switcher).toHaveAttribute("title", "Liste wechseln");
    await expect(access).toHaveAttribute("title", "Zugriff verwalten");
    for (const control of [switcher, access]) {
      const box = await control.boundingBox();
      const target = width <= 800 ? 44 : 32;
      expect(box.width).toBeGreaterThanOrEqual(target);
      expect(box.height).toBeGreaterThanOrEqual(target);
    }
    await page
      .getByRole("button", { name: /^Aufgabe anlegen/ })
      .first()
      .click();
    const quickForm = page.getByRole("form", {
      name: "Aufgabe schnell erfassen",
    });
    await expect(quickForm).toBeVisible();
    // On a list page the list is fixed: no picker.
    await expect(quickForm.getByLabel("Aufgabenliste")).toHaveCount(0);
    const quickBox = await quickForm.boundingBox();
    if (width <= 720) {
      expect(quickBox.height).toBeGreaterThanOrEqual(44);
    }
    await quickForm.getByLabel("Titel", { exact: true }).press("Escape");
    await expect(quickForm).toHaveCount(0);
    if (surface === "app") {
      // Tasks live in the "Mehr" sheet; the tab bar stays in the viewport.
      const tabbar = page.locator(".pwa-tabs");
      await expect(tabbar).toBeVisible();
      const tabbarBox = await tabbar.boundingBox();
      expect(tabbarBox.x).toBeGreaterThanOrEqual(0);
      expect(tabbarBox.x + tabbarBox.width).toBeLessThanOrEqual(width + 1);
      await page.getByTestId("pwa-menu").click();
      const sheet = page.getByRole("dialog", { name: "Mehr" });
      const taskNavigation = sheet.getByRole("link", { name: "Aufgaben" });
      await expect(taskNavigation).toHaveAttribute("aria-current", "page");
      const taskBox = await taskNavigation.boundingBox();
      expect(taskBox.width).toBeGreaterThanOrEqual(44);
      expect(taskBox.height).toBeGreaterThanOrEqual(44);
      await sheet.getByRole("button", { name: "Schließen" }).click();
      await expect(sheet).toBeHidden();
    }
    await switcher.click();
    await expect(switcher).toHaveAttribute("aria-expanded", "true");
    await expect(
      page.getByRole("heading", { name: "Aufgabenliste wechseln" }),
    ).toBeVisible();
    await switcher.click();
    await expect(
      page.getByRole("heading", { name: "Aufgabenliste wechseln" }),
    ).toHaveCount(0);

    const target = taskRowLink(page, { id: tasks[3].id });
    await target.scrollIntoViewIfNeeded();
    const returnScroll = await page.evaluate(() => window.scrollY);
    const pane = await openTask(page, { id: tasks[3].id });
    await expect(page).toHaveURL(/open=/);
    const editor = pane.getByRole("form", { name: "Aufgabe bearbeiten" });
    await expect(editor).toBeVisible();
    if (width <= 720) {
      // Phone: the pane is a full-screen sheet with reachable actions.
      const sheet = page.locator("dialog.pane-sheet");
      await expect(sheet).toBeVisible();
      const sheetBox = await sheet.boundingBox();
      expect(sheetBox.width).toBeGreaterThanOrEqual(width - 1);
      const editorActions = editor
        .getByRole("button", { name: "Speichern" })
        .locator("..");
      await editorActions.scrollIntoViewIfNeeded();
      const actionsBox = await editorActions.boundingBox();
      expect(actionsBox.y + actionsBox.height).toBeLessThanOrEqual(
        page.viewportSize().height,
      );
      await page.screenshot({
        path: testInfo.outputPath(`s2-${surface}-${width}-detail-actions.png`),
        fullPage: false,
      });
      await editor
        .getByRole("textbox", { name: "Titel", exact: true })
        .scrollIntoViewIfNeeded();
    } else if (width > 1180) {
      // Wide: list and pane side by side.
      expect(
        (await page.locator(".listview-main").boundingBox()).width,
      ).toBeGreaterThanOrEqual(360);
      await expect(target).toBeVisible();
    }
    await page.screenshot({
      path: testInfo.outputPath(`s2-${surface}-${width}-detail.png`),
      fullPage: false,
    });

    const description = editor.getByLabel("Beschreibung");
    await description.fill("Dieser Entwurf muss erhalten bleiben");
    if (surface === "admin") {
      const other = await signedInContext(browser, width, 1);
      const otherIdentityResponse = await other.request.get(
        `${baseURL}/api/v1/identity/me`,
      );
      expect(otherIdentityResponse.ok()).toBe(true);
      const otherIdentity = await otherIdentityResponse.json();
      const grant = await context.request.put(
        `${baseURL}/api/v1/task-lists/${list.id}/members`,
        {
          headers: { Origin: baseURL },
          data: {
            userId: otherIdentity.userId,
            access: "editor",
            expectedRevision: list.revision,
            idempotencyKey: randomUUID(),
          },
        },
      );
      expect(grant.ok()).toBe(true);
      const original = tasks[3];
      const competing = await other.request.put(
        `${baseURL}/api/v1/tasks/${original.id}`,
        {
          headers: { Origin: baseURL },
          data: {
            title: `${original.title} – parallel geändert`,
            description: original.description,
            status: original.status,
            assigneeUserId: original.assigneeUserId,
            epicId: original.epicId,
            dueAt: original.dueAt,
            deferredUntil: original.deferredUntil,
            expectedRevision: original.revision,
            idempotencyKey: randomUUID(),
          },
        },
      );
      expect(competing.ok()).toBe(true);
      await editor.getByRole("button", { name: "Speichern" }).click();
      await expect(editor).toContainText("inzwischen geändert");
      await expect(description).toHaveValue(
        "Dieser Entwurf muss erhalten bleiben",
      );
      await other.close();
    }
    // Back with a draft asks first; dismissing keeps pane and draft.
    page.once("dialog", async (dialog) => {
      expect(dialog.message()).toContain("verwerfen");
      await dialog.dismiss();
    });
    await page.goBack();
    await expect(page).toHaveURL(/open=/);
    await expect(description).toHaveValue(
      "Dieser Entwurf muss erhalten bleiben",
    );
    if (width > 720) {
      // Esc leaves the field first, then asks before closing the pane.
      await description.press("Escape");
      await expect(description).not.toBeFocused();
      page.once("dialog", async (dialog) => {
        expect(dialog.message()).toContain("verwerfen");
        await dialog.dismiss();
      });
      await page.keyboard.press("Escape");
      await expect(description).toHaveValue(
        "Dieser Entwurf muss erhalten bleiben",
      );
    }

    if (surface === "app") {
      // The task sheet is modal: the shell's tabs and sheet links are out
      // of reach until it closes, and closing asks about the draft.
      expect(
        await page.evaluate(() =>
          document.querySelector("dialog.pane-sheet")?.matches(":modal"),
        ),
      ).toBe(true);
    }

    page.once("dialog", async (dialog) => dialog.accept());
    await editor.getByRole("button", { name: "Abbrechen" }).click();
    await expect(taskPane(page)).toHaveCount(0);
    await expect(page).not.toHaveURL(/open=/);
    await expect(page).toHaveURL(/q=Detail/);
    await expect(target).toBeFocused();
    expect(await page.evaluate(() => window.scrollY)).toBeGreaterThanOrEqual(
      Math.max(0, returnScroll - 2),
    );
    await expect(taskRow(page, tasks[3].id)).toBeVisible();

    await page.evaluate(() => window.scrollTo({ top: 0 }));
    await page.screenshot({
      path: testInfo.outputPath(`s2-${surface}-workspace.png`),
      fullPage: false,
    });
    if (surface === "app") {
      // A typed search loses nothing: a tab leaves without the shell asking.
      const dialogs = [];
      page.on("dialog", (dialog) => {
        dialogs.push(dialog.message());
        void dialog.dismiss();
      });
      await taskSearch(page).fill("Detail 0");
      await page
        .getByRole("navigation", { name: "App-Navigation" })
        .getByRole("link", { name: "Start" })
        .click();
      await expect(page).toHaveURL(/\/app\/(\?.*)?$/);
      expect(dialogs).toEqual([]);
      await expect(page.getByRole("alertdialog")).toHaveCount(0);
    }
    await context.close();
  });
}
