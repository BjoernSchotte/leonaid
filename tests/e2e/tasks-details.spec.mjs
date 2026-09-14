import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";

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
  const identityResponse = await context.request.get(
    `${baseURL}/api/v1/identity/me`,
  );
  expect(identityResponse.ok()).toBe(true);
  const identity = await identityResponse.json();
  const page = await context.newPage();
  await page.goto(`${baseURL}/admin/tasks?scope=mine&view=open`);

  const quick = page.getByRole("form", { name: "Aufgabe schnell erfassen" });
  await expect(quick).toBeVisible();
  let writes = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      /\/task-lists\/[^/]+\/tasks$/.test(request.url())
    )
      writes += 1;
  });
  await quick.getByLabel("Titel").press("Enter");
  expect(writes).toBe(0);
  await quick.getByLabel("Aufgabenliste").selectOption(list.id);
  await expect(quick.getByLabel("Zuständigkeit")).toHaveValue(identity.userId);
  const title = `S2 Schnellerfassung ${randomUUID()}`;
  await quick.getByLabel("Titel").fill(title);
  await quick.getByLabel("Titel").press("Enter");
  await expect.poll(() => writes).toBe(1);
  await expect(
    page.getByRole("heading", { name: title, exact: true }),
  ).toBeVisible();
  await expect(page).toHaveURL(/scope=mine/);
  await expect(page).toHaveURL(/view=open/);

  await page.getByLabel("Aufgaben suchen").fill(title);
  await expect
    .poll(() => new URL(page.url()).searchParams.get("search"))
    .toBe(title);
  await page.reload();
  await expect(page.getByLabel("Aufgaben suchen")).toHaveValue(title);
  await expect(
    page.getByRole("heading", { name: title, exact: true }),
  ).toBeVisible();
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
    await page.goto(
      `${baseURL}/${surface}/tasks/${list.id}?scope=all&view=open&search=Detail`,
    );

    const switcher = page.getByRole("button", { name: "Liste wechseln" });
    const access = page.getByRole("button", { name: "Zugriff verwalten" });
    await expect(switcher).toHaveAttribute("title", "Liste wechseln");
    await expect(access).toHaveAttribute("title", "Zugriff verwalten");
    for (const control of [switcher, access]) {
      const box = await control.boundingBox();
      expect(box.width).toBeGreaterThanOrEqual(44);
      expect(box.height).toBeGreaterThanOrEqual(44);
    }
    const quickSubmit = page.getByRole("button", { name: "Neue Aufgabe" });
    const quickForm = page.getByRole("form", {
      name: "Aufgabe schnell erfassen",
    });
    await expect(quickForm.locator(".task-quick-context")).toHaveCount(0);
    const quickSubmitBox = await quickSubmit.boundingBox();
    const quickFormBox = await quickForm.boundingBox();
    const quickTitleBox = await quickForm.getByLabel("Titel").boundingBox();
    const quickAssigneeBox = await quickForm
      .getByLabel("Zuständigkeit")
      .boundingBox();
    expect(quickSubmitBox.height).toBeLessThanOrEqual(48);
    expect(quickSubmitBox.width).toBeLessThanOrEqual(200);
    expect(quickSubmitBox.y).toBeGreaterThanOrEqual(quickAssigneeBox.y - 2);
    if (width <= 1024) {
      expect(quickTitleBox.width).toBeGreaterThanOrEqual(
        quickFormBox.width * 0.9,
      );
    }
    if (surface === "app") {
      expect(quickAssigneeBox.width).toBeGreaterThanOrEqual(
        quickFormBox.width * 0.9,
      );
    }
    expect(
      await quickSubmit.evaluate(
        (button) => button.scrollWidth <= button.clientWidth,
      ),
    ).toBe(true);
    if (surface === "app") {
      const tabbar = page.locator(".ui-pwa-tabbar");
      const taskNavigation = tabbar.getByRole("link", { name: "Aufgaben" });
      await expect(tabbar).toBeVisible();
      await expect(taskNavigation).toBeVisible();
      const tabbarBox = await tabbar.boundingBox();
      const taskNavigationBox = await taskNavigation.boundingBox();
      expect(taskNavigationBox.x + taskNavigationBox.width).toBeLessThanOrEqual(
        tabbarBox.x + tabbarBox.width,
      );
      expect(
        taskNavigationBox.y + taskNavigationBox.height,
      ).toBeLessThanOrEqual(tabbarBox.y + tabbarBox.height);
      expect(
        await taskNavigation
          .locator("span")
          .evaluate((label) => label.scrollWidth <= label.clientWidth),
      ).toBe(true);
    }
    if (width <= 1024) {
      const scopeBox = await page.getByLabel("Bereich").boundingBox();
      const statusBox = await page.getByLabel("Ansicht").boundingBox();
      const searchBox = await page.getByLabel("Aufgaben suchen").boundingBox();
      expect(Math.abs(scopeBox.y - statusBox.y)).toBeLessThanOrEqual(2);
      expect(searchBox.y).toBeGreaterThan(scopeBox.y + scopeBox.height);
    }
    await switcher.click();
    await expect(switcher).toHaveAttribute("aria-expanded", "true");
    await expect(
      page.getByRole("heading", { name: "Aufgabenliste wechseln" }),
    ).toBeVisible();
    await switcher.click();

    const target = page.getByRole("button", {
      name: "S2 Detail 04",
      exact: true,
    });
    await target.scrollIntoViewIfNeeded();
    const returnScroll = await page.evaluate(() => window.scrollY);
    await target.click();
    await expect(page).toHaveURL(/task=/);
    const editor = page.getByRole("form", { name: "Aufgabe bearbeiten" });
    await expect(editor).toBeVisible();
    if (surface === "app") {
      await expect(page.locator(".ui-pwa-tabbar")).toBeHidden();
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
    }
    const workspaceWidth = (
      await page.locator(".tasks-workspace").boundingBox()
    ).width;
    if (workspaceWidth >= 720) {
      await expect(page.locator(".tasks-main")).toBeVisible();
      expect(
        (await page.locator(".tasks-main").boundingBox()).width,
      ).toBeGreaterThanOrEqual(360);
    } else {
      await expect(page.locator(".tasks-main")).toBeHidden();
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
    page.once("dialog", async (dialog) => {
      expect(dialog.message()).toContain("verwerfen");
      await dialog.dismiss();
    });
    await page.goBack();
    await expect(description).toHaveValue(
      "Dieser Entwurf muss erhalten bleiben",
    );
    await description.press("Escape");
    await expect(description).toHaveValue(
      "Dieser Entwurf muss erhalten bleiben",
    );

    page.once("dialog", async (dialog) => dialog.accept());
    await editor.getByRole("button", { name: "Abbrechen" }).click();
    await expect(editor).toHaveCount(0);
    await expect(page).toHaveURL(/scope=all/);
    await expect(page).toHaveURL(/view=open/);
    await expect(page).toHaveURL(/search=Detail/);
    if (surface === "app") {
      await expect(page.locator(".ui-pwa-tabbar")).toBeVisible();
    }
    await expect(target).toBeFocused();
    expect(await page.evaluate(() => window.scrollY)).toBeGreaterThanOrEqual(
      Math.max(0, returnScroll - 2),
    );

    await page.evaluate(() => window.scrollTo({ top: 0 }));
    await page.screenshot({
      path: testInfo.outputPath(`s2-${surface}-workspace.png`),
      fullPage: false,
    });
    await context.close();
  });
}
