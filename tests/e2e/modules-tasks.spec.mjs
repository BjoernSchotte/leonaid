import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
const fixture = JSON.parse(
  readFileSync(process.env.LEONAID_MODULE_FIXTURE, "utf8"),
);
const baseURL = process.env.LEONAID_E2E_BASE_URL;
for (const [surface, width] of [
  ["admin", 1440],
  ["app", 390],
]) {
  test(`${surface}: assign, defer and complete task without changing due date`, async ({
    browser,
  }, testInfo) => {
    const context = await browser.newContext({
      viewport: { width, height: 844 },
      timezoneId: "UTC",
      ignoreHTTPSErrors: true,
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
    const page = await context.newPage();
    const title = `Aufgabe Browsernachweis ${randomUUID()}`;
    const due = new Date(Date.now() + 86400000 * 10).toISOString().slice(0, 16);
    const deferred = new Date(Date.now() + 86400000 * 2)
      .toISOString()
      .slice(0, 16);
    await page.goto(`${baseURL}/${surface}/tasks`);
    await page.getByRole("button", { name: "Liste wechseln" }).click();
    await page.getByText("Neue Liste", { exact: true }).click();
    await page
      .getByLabel("Name der Liste", { exact: true })
      .fill(`Liste ${title}`);
    await page
      .getByRole("button", { name: "Liste anlegen", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: `Liste ${title}`, exact: true }),
    ).toBeVisible();
    const quick = page.getByRole("form", {
      name: "Aufgabe schnell erfassen",
      exact: true,
    });
    await quick.getByLabel("Titel", { exact: true }).fill(title);
    await quick.getByLabel("Titel", { exact: true }).press("Enter");
    const taskHeading = page.getByRole("heading", { name: title, exact: true });
    await expect(taskHeading).toBeVisible();
    await taskHeading.getByRole("button", { name: title, exact: true }).click();
    const editor = page.getByRole("form", {
      name: "Aufgabe bearbeiten",
      exact: true,
    });
    await editor.getByText("Zuständigkeit auswählen", { exact: true }).click();
    const assignee = editor.getByRole("combobox", {
      name: "Zuständige Person",
      exact: true,
    });
    await expect(
      assignee.locator("option").filter({ hasText: "(ich)" }),
    ).toHaveCount(1);
    await assignee.selectOption({
      label: await assignee
        .locator("option")
        .filter({ hasText: "(ich)" })
        .textContent(),
    });
    await editor
      .getByText("Termine und Wiedervorlage", { exact: true })
      .click();
    await editor.getByLabel("Fällig am", { exact: true }).fill(due);
    await editor
      .getByLabel("Zurückgestellt bis", { exact: true })
      .fill(deferred);
    await editor
      .getByRole("button", { name: "Speichern", exact: true })
      .click();
    await expect(editor).toHaveCount(0);
    await page
      .getByRole("combobox", { name: "Bereich", exact: true })
      .selectOption("mine");
    await expect(
      page.getByRole("heading", { name: title, exact: true }),
    ).toHaveCount(0);
    await page
      .getByRole("combobox", { name: "Ansicht", exact: true })
      .selectOption("deferred");
    const row = page
      .locator(".tasks-results li")
      .filter({ has: page.getByRole("heading", { name: title, exact: true }) });
    await expect(row).toBeVisible();
    await row.getByRole("button", { name: title, exact: true }).click();
    const edit = page.getByRole("form", {
      name: "Aufgabe bearbeiten",
      exact: true,
    });
    await edit.getByText("Termine und Wiedervorlage", { exact: true }).click();
    await expect(edit.getByLabel("Fällig am", { exact: true })).toHaveValue(
      due,
    );
    await expect(
      edit.getByLabel("Zurückgestellt bis", { exact: true }),
    ).toHaveValue(deferred);
    await edit.getByLabel("Zurückgestellt bis", { exact: true }).fill("");
    await edit
      .getByRole("combobox", { name: "Status", exact: true })
      .selectOption("done");
    await edit.getByRole("button", { name: "Speichern", exact: true }).click();
    await expect(edit).toHaveCount(0);
    await page
      .getByRole("combobox", { name: "Ansicht", exact: true })
      .selectOption("done");
    await expect(row).toContainText("Erledigt");
    await row.getByRole("button", { name: title, exact: true }).click();
    await expect(edit.getByLabel("Fällig am", { exact: true })).toHaveValue(
      due,
    );
    await expect(
      edit.getByLabel("Zurückgestellt bis", { exact: true }),
    ).toHaveValue("");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath(`${surface}-task-completed.png`),
      fullPage: false,
    });
    await context.close();
  });
}

for (const [surface, width] of [
  ["admin", 1440],
  ["app", 390],
]) {
  test(`${surface}: S1 compact rows, status undo and concurrent conflict`, async ({
    browser,
  }, testInfo) => {
    const context = await browser.newContext({
      viewport: { width, height: 844 },
      ignoreHTTPSErrors: true,
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
    const headers = { Origin: baseURL };
    const listResponse = await context.request.post(
      `${baseURL}/api/v1/task-lists`,
      {
        headers,
        data: { title: `S1 ${randomUUID()}`, idempotencyKey: randomUUID() },
      },
    );
    expect(listResponse.ok()).toBe(true);
    const list = await listResponse.json();
    const epicResponse = await context.request.post(
      `${baseURL}/api/v1/task-lists/${list.id}/epics`,
      {
        headers,
        data: { title: "Vorbereitung", idempotencyKey: randomUUID() },
      },
    );
    const epic = await epicResponse.json();
    const originals = [];
    for (let i = 0; i < 12; i++) {
      const response = await context.request.post(
        `${baseURL}/api/v1/task-lists/${list.id}/tasks`,
        {
          headers,
          data: {
            title:
              i === 1
                ? "Langer deutscher Aufgabentitel ".repeat(9).slice(0, 240)
                : `Vorbereitung ${i + 1}`,
            description: "Beschreibung bleibt vollständig erhalten.",
            epicId: i === 2 ? null : epic.id,
            dueAt: i === 2 ? null : "2030-06-01T10:00:00Z",
            idempotencyKey: randomUUID(),
          },
        },
      );
      expect(response.ok()).toBe(true);
      originals.push(await response.json());
    }
    const page = await context.newPage();
    const readRequests = [];
    page.on("request", (request) => {
      if (request.method() === "GET" && request.url().includes("/api/v1/"))
        readRequests.push(request.url());
    });
    await page.goto(`${baseURL}/${surface}/tasks/${list.id}`);
    const first = originals[0];
    const checkbox = page.getByRole("checkbox", {
      name: `Aufgabe abschließen: ${first.title}`,
      exact: true,
    });
    await expect(checkbox).toBeVisible();
    const newTaskButton = page.getByRole("button", {
      name: "Neue Aufgabe",
      exact: true,
    });
    const newTaskBox = await newTaskButton.boundingBox();
    expect(newTaskBox.height).toBeGreaterThanOrEqual(width <= 760 ? 44 : 40);
    expect(newTaskBox.height).toBeLessThanOrEqual(width <= 760 ? 48 : 44);
    const iconBox = await newTaskButton
      .locator(".ui-button__icon")
      .boundingBox();
    const textBox = await newTaskButton
      .locator("span")
      .filter({ hasText: /^Neue Aufgabe$/ })
      .boundingBox();
    expect(iconBox.x + iconBox.width).toBeLessThanOrEqual(textBox.x);
    expect(
      Math.abs(iconBox.y + iconBox.height / 2 - textBox.y - textBox.height / 2),
    ).toBeLessThanOrEqual(2);
    expect(
      await page.getByLabel("Name der Liste", { exact: true }).isVisible(),
    ).toBe(false);
    const box = await checkbox.boundingBox();
    expect(box.width).toBeGreaterThanOrEqual(44);
    expect(box.height).toBeGreaterThanOrEqual(44);
    expect(box.y + box.height).toBeLessThan(844);
    await expect(page.locator(".tasks-results > li")).toHaveCount(12);
    const minimalTitle = page.getByRole("button", {
      name: originals[2].title,
      exact: true,
    });
    const minimalRow = page
      .locator(".tasks-results > li")
      .filter({ has: minimalTitle });
    const minimalRowBox = await minimalRow.boundingBox();
    expect(minimalRowBox.height).toBeGreaterThanOrEqual(width <= 760 ? 56 : 44);
    expect(minimalRowBox.height).toBeLessThanOrEqual(width <= 760 ? 64 : 56);
    expect((await minimalTitle.boundingBox()).height).toBeGreaterThanOrEqual(
      44,
    );
    await expect(minimalTitle).toHaveAccessibleDescription("Nicht zugewiesen");
    await expect(minimalRow.getByText("Offen", { exact: true })).toHaveCount(0);

    expect(
      readRequests.filter((url) => /\/tasks\/[^?]+|\/epics/.test(url)),
    ).toHaveLength(0);
    expect(
      readRequests.filter((url) => url.includes("/assignees")),
    ).toHaveLength(1);
    await page.screenshot({
      path: testInfo.outputPath(
        surface === "admin" ? "s1-desktop-list.png" : "s1-pwa-list.png",
      ),
    });
    await page.setViewportSize({ width: 320, height: 844 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await expect(
      page.getByRole("heading", { name: originals[1].title, exact: true }),
    ).toBeVisible();
    await page.setViewportSize({ width, height: 844 });
    // Real requests stay slow at the browser transport; no intercepted/fake
    // responses. A connection-restored signal triggers the query refetch.
    const cdp = await context.newCDPSession(page);
    await cdp.send("Network.enable");
    await cdp.send("Network.emulateNetworkConditions", {
      offline: false,
      latency: 1500,
      downloadThroughput: 1024 * 1024,
      uploadThroughput: 1024 * 1024,
    });
    const refreshStarted = page.waitForRequest(
      (request) =>
        request.method() === "GET" &&
        new URL(request.url()).pathname === "/api/v1/tasks",
    );
    const refreshFinished = page.waitForResponse(
      (response) =>
        response.request().method() === "GET" &&
        new URL(response.url()).pathname === "/api/v1/tasks",
    );
    const searchField = page.getByLabel("Aufgaben suchen", { exact: true });
    await searchField.focus();
    await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await refreshStarted;
    await expect(page.locator(".tasks-results > li")).toHaveCount(12);
    await expect(checkbox).toBeVisible();
    await expect(
      page.getByText("Aufgaben werden geladen …", { exact: true }),
    ).toHaveCount(0);
    expect((await refreshFinished).ok()).toBe(true);
    await expect(searchField).toBeFocused();
    await cdp.send("Network.emulateNetworkConditions", {
      offline: false,
      latency: 0,
      downloadThroughput: -1,
      uploadThroughput: -1,
    });
    await cdp.detach();
    const writes = [];
    page.on("request", (request) => {
      if (
        request.method() === "PUT" &&
        request.url().endsWith(`/tasks/${first.id}`)
      )
        writes.push(request.postDataJSON());
    });
    await expect(checkbox).toBeEnabled();
    await checkbox.focus();
    await expect(checkbox).toBeFocused();
    await checkbox.dblclick();
    await expect(
      page.getByRole("button", { name: "Rückgängig", exact: true }),
    ).toBeVisible();
    expect(writes).toHaveLength(1);
    await expect(
      page.getByRole("button", { name: "Rückgängig", exact: true }),
    ).not.toBeFocused();
    await expect(
      page.getByRole("form", { name: "Aufgabe bearbeiten", exact: true }),
    ).toHaveCount(0);
    await page.screenshot({
      path: testInfo.outputPath(`s1-${surface}-undo.png`),
    });
    const read = async () =>
      (await context.request.get(`${baseURL}/api/v1/tasks/${first.id}`)).json();
    const preserved = (task) =>
      Object.fromEntries(
        Object.entries(task).filter(
          ([key]) => !["status", "revision", "updatedAt"].includes(key),
        ),
      );
    expect(preserved(await read())).toEqual(preserved(first));
    await page
      .getByRole("button", { name: "Rückgängig", exact: true })
      .dblclick();
    await expect(checkbox).toBeVisible();
    expect(writes).toHaveLength(2);
    expect((await read()).revision).toBe(first.revision + 2);
    expect(preserved(await read())).toEqual(preserved(first));
    // Actual keyboard activation, then deterministic continuation after both
    // controls disappear. Pointer double-click coverage above remains separate.
    await expect(checkbox).toBeEnabled();
    await checkbox.focus();
    await page.keyboard.press("Space");
    const undoAction = page.getByRole("button", {
      name: "Rückgängig",
      exact: true,
    });
    await expect(undoAction).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(checkbox).toBeFocused();
    expect(writes).toHaveLength(4);
    expect((await read()).revision).toBe(first.revision + 4);
    expect(preserved(await read())).toEqual(preserved(first));
    // Moving elsewhere during a slow keyboard-triggered save cancels its
    // focus destination; the eventual response must not pull focus back.
    const slowSave = await context.newCDPSession(page);
    await slowSave.send("Network.enable");
    await slowSave.send("Network.emulateNetworkConditions", {
      offline: false,
      latency: 750,
      downloadThroughput: 1024 * 1024,
      uploadThroughput: 1024 * 1024,
    });
    await page.keyboard.press("Space");
    await searchField.click();
    await expect(undoAction).toBeEnabled();
    await expect(searchField).toBeFocused();
    await slowSave.send("Network.emulateNetworkConditions", {
      offline: false,
      latency: 0,
      downloadThroughput: -1,
      uploadThroughput: -1,
    });
    await slowSave.detach();
    await undoAction.click();
    await expect(checkbox).toBeEnabled();
    await page.reload();
    await expect(checkbox).toBeEnabled();
    // This server-controlled checkbox disappears from the open view on success;
    // check() would require an immediate client-side checked state instead.
    await checkbox.click();
    await expect(
      page.getByRole("button", { name: "Rückgängig", exact: true }),
    ).toBeVisible();
    await expect(checkbox).toHaveCount(0);
    const completed = await read();
    expect(completed.status).toBe("done");
    expect(completed.revision).toBe(first.revision + 7);
    expect(writes).toHaveLength(7);
    const {
      title,
      description,
      epicId,
      assigneeUserId,
      dueAt,
      deferredUntil,
      status,
    } = completed;
    const second = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width, height: 844 },
    });
    await second.addCookies([
      {
        name: "__Host-leonaid_session",
        value: fixture.sessions[1],
        url: baseURL,
        secure: true,
        httpOnly: true,
        sameSite: "Lax",
      },
    ]);
    const secondIdentity = await (
      await second.request.get(`${baseURL}/api/v1/identity/me`)
    ).json();
    const membershipPath = `${baseURL}/api/v1/task-lists/${list.id}/members`;
    const grant = await context.request.put(membershipPath, {
      headers,
      data: {
        userId: secondIdentity.userId,
        access: "viewer",
        expectedRevision: 1,
        idempotencyKey: randomUUID(),
      },
    });
    expect(grant.ok()).toBe(true);
    const readerPage = await second.newPage();
    await readerPage.goto(`${baseURL}/${surface}/tasks/${list.id}`);
    await expect(
      readerPage.getByRole("heading", { name: list.title, exact: true }),
    ).toBeVisible();
    await expect(
      readerPage.getByRole("button", { name: "Neue Aufgabe", exact: true }),
    ).toHaveCount(0);
    await expect(
      readerPage.getByRole("form", { name: "Aufgabe schnell erfassen" }),
    ).toHaveCount(0);
    await expect(
      readerPage.getByRole("button", { name: "Bearbeiten", exact: true }),
    ).toHaveCount(0);
    await expect(
      readerPage.getByRole("checkbox", { name: /^Aufgabe abschließen:/ }),
    ).toHaveCount(0);
    const lowerTitle = readerPage.getByRole("button", {
      name: originals[11].title,
      exact: true,
    });
    await lowerTitle.focus();
    await readerPage.keyboard.press("Enter");
    const readerDetail = readerPage.locator(".task-read-only");
    const detailHeading = readerDetail.getByRole("heading", {
      name: originals[11].title,
      exact: true,
    });
    await expect(detailHeading).toBeFocused();
    expect((await detailHeading.boundingBox()).y).toBeGreaterThanOrEqual(0);
    expect((await detailHeading.boundingBox()).y).toBeLessThan(844);
    await readerPage.keyboard.press("Tab");
    await expect(
      readerPage.getByRole("button", { name: "Schließen", exact: true }),
    ).toBeFocused();
    await readerPage.keyboard.press("Enter");
    await expect(readerDetail).toHaveCount(0);
    await expect(lowerTitle).toBeFocused();
    await readerPage.goto(
      `${baseURL}/${surface}/tasks/${list.id}?task=${first.id}`,
    );
    await expect(
      readerPage.getByRole("heading", { name: first.title, exact: true }),
    ).toBeVisible();
    await expect(
      readerPage.getByRole("button", { name: "Speichern", exact: true }),
    ).toHaveCount(0);
    await expect(readerPage.getByLabel("Titel", { exact: true })).toHaveCount(
      0,
    );
    const promotion = await context.request.put(membershipPath, {
      headers,
      data: {
        userId: secondIdentity.userId,
        access: "editor",
        expectedRevision: 2,
        idempotencyKey: randomUUID(),
      },
    });
    expect(promotion.ok()).toBe(true);
    const changedResponse = await second.request.put(
      `${baseURL}/api/v1/tasks/${first.id}`,
      {
        headers,
        data: {
          title: `${title} – inzwischen geändert`,
          description,
          epicId,
          assigneeUserId,
          dueAt,
          deferredUntil,
          status,
          expectedRevision: completed.revision,
          idempotencyKey: randomUUID(),
        },
      },
    );
    expect(changedResponse.ok()).toBe(true);
    const changed = await changedResponse.json();
    const conflict = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/tasks/${first.id}`) &&
        response.status() === 409,
    );
    await page.getByRole("button", { name: "Rückgängig", exact: true }).click();
    await conflict;
    await expect(page.getByText(/inzwischen geändert/)).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Neu laden", exact: true }),
    ).toBeVisible();
    expect(await read()).toEqual(changed);
    await page.getByRole("button", { name: "Neu laden", exact: true }).click();
    await page
      .getByLabel("Aufgaben suchen", { exact: true })
      .fill("kein passender Titel");
    await expect(
      page.getByText("Keine Aufgaben für diese Suche.", { exact: true }),
    ).toBeVisible();
    await second.close();
    await context.close();
  });
}
