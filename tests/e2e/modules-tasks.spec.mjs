import { test, expect } from "./csp-guard.mjs";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import {
  horizontalOverflow,
  openTask,
  pickOption,
  showTaskView,
  taskPane,
  taskRow,
  taskRowLink,
  taskRows,
  taskSearch,
} from "./task-list.mjs";
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
    await page
      .getByRole("button", { name: /^Aufgabe anlegen/ })
      .first()
      .click();
    const quick = page.getByRole("form", {
      name: "Aufgabe schnell erfassen",
      exact: true,
    });
    await quick.getByLabel("Neue Aufgabe", { exact: true }).fill(title);
    const createdResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        /\/task-lists\/[^/]+\/tasks$/.test(response.url()) &&
        response.ok(),
    );
    await quick.getByLabel("Neue Aufgabe", { exact: true }).press("Enter");
    const createdTask = await (await createdResponse).json();
    await expect(taskRow(page, createdTask.id)).toBeVisible();
    // Esc leaves the quick add; the list keys work again.
    await quick.getByLabel("Neue Aufgabe", { exact: true }).press("Escape");
    await expect(quick).toHaveCount(0);

    let pane = await openTask(page, { id: createdTask.id });
    const editor = pane.locator("form.task-editor");
    await expect(editor).toBeVisible();
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
    const epicTitle = `S4 Abschnitt ${randomUUID()}`;
    await editor.getByText("Abschnitt auswählen", { exact: true }).click();
    await editor.getByLabel("Titel des Abschnitts", { exact: true }).fill(epicTitle);
    const createdEpicResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        /\/task-lists\/[^/]+\/epics$/.test(response.url()) &&
        response.ok(),
    );
    await editor
      .getByRole("button", { name: "Abschnitt anlegen", exact: true })
      .click();
    const createdEpic = await (await createdEpicResponse).json();
    await expect(editor.locator(".task-epic-picker select")).toHaveValue(
      createdEpic.id,
    );
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
    await expect(
      page.getByText("Aufgabe gespeichert.", { exact: true }),
    ).toBeVisible();
    // Deferred now: "Offen" hides it, the pane keeps the record.
    await page.keyboard.press("Escape");
    await expect(taskPane(page)).toHaveCount(0);
    await expect(taskRow(page, createdTask.id)).toHaveCount(0);

    await page.goto(
      `${baseURL}/${surface}/tasks/${createdTask.listId}?f.status=open&f.deferral=deferred&f.assignee=${createdTask.createdBy}`,
    );
    await taskSearch(page).fill(title);
    const row = taskRow(page, createdTask.id);
    await expect(row).toBeVisible();
    await expect(row).toContainText(epicTitle);
    pane = await openTask(page, { id: createdTask.id });
    const edit = pane.locator("form.task-editor");
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
    await expect(
      page.getByText("Aufgabe gespeichert.", { exact: true }),
    ).toBeVisible();

    await page.goto(`${baseURL}/${surface}/tasks/${createdTask.listId}`);
    await showTaskView(page, "Erledigt");
    await expect(row).toContainText(title);
    await expect(row.locator(".is-struck")).toHaveText(title);
    pane = await openTask(page, { id: createdTask.id });
    const reopen = pane.locator("form.task-editor");
    await reopen
      .getByText("Termine und Wiedervorlage", { exact: true })
      .click();
    await expect(reopen.getByLabel("Fällig am", { exact: true })).toHaveValue(
      due,
    );
    await expect(
      reopen.getByLabel("Zurückgestellt bis", { exact: true }),
    ).toHaveValue("");
    await reopen
      .getByRole("combobox", { name: "Status", exact: true })
      .selectOption("open");
    await reopen
      .getByRole("button", { name: "Speichern", exact: true })
      .click();
    await expect(
      page.getByText("Aufgabe gespeichert.", { exact: true }),
    ).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(taskPane(page)).toHaveCount(0);
    await showTaskView(page, "Offen");
    await expect(row).toBeVisible();
    // "Offen" groups by section.
    await expect(
      page.locator(".group-header", { hasText: epicTitle }),
    ).toHaveCount(1);
    const finalResponse = await context.request.get(
      `${baseURL}/api/v1/tasks/${createdTask.id}`,
    );
    expect(finalResponse.ok()).toBe(true);
    const finalTask = await finalResponse.json();
    expect(finalTask.status).toBe("open");
    expect(finalTask.epicId).toBe(createdEpic.id);
    expect(new Date(finalTask.dueAt).getTime()).toBe(new Date(due).getTime());
    expect(finalTask.deferredUntil).toBeNull();
    expect(await horizontalOverflow(page)).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath(`s4-${surface}-foundation-flow.png`),
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
    await expect(taskRows(page)).toHaveCount(12);
    const create = page.getByRole("button", { name: /^Aufgabe anlegen/ });
    const createBox = await create.boundingBox();
    expect(createBox.height).toBeGreaterThanOrEqual(width <= 760 ? 44 : 32);
    expect(createBox.height).toBeLessThanOrEqual(width <= 760 ? 48 : 40);
    expect(
      await page.getByLabel("Name der Liste", { exact: true }).count(),
    ).toBe(0);
    // Compact rows: 40 px on desktop, two lines on the phone.
    const minimalRow = taskRow(page, originals[2].id);
    const minimalRowBox = await minimalRow.boundingBox();
    expect(minimalRowBox.height).toBeGreaterThanOrEqual(width <= 760 ? 56 : 40);
    // Phone: grip (44 px target), title and the chip line.
    expect(minimalRowBox.height).toBeLessThanOrEqual(width <= 760 ? 96 : 44);
    await expect(
      minimalRow.locator('.avatar-empty[aria-label="Niemand zuständig"]'),
    ).toBeVisible();
    // The list is read from list endpoints only: no task or epic detail reads.
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
    expect(await horizontalOverflow(page)).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await expect(taskRowLink(page, { id: originals[1].id })).toBeVisible();
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
    const searchField = taskSearch(page);
    await searchField.focus();
    await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await refreshStarted;
    // The rows stay while the list refreshes; no skeleton, focus kept.
    await expect(taskRows(page)).toHaveCount(12);
    await expect(page.locator(".skeleton-list")).toHaveCount(0);
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
    const read = async () =>
      (await context.request.get(`${baseURL}/api/v1/tasks/${first.id}`)).json();
    const preserved = (task) =>
      Object.fromEntries(
        Object.entries(task).filter(
          ([key]) => !["status", "revision", "updatedAt"].includes(key),
        ),
      );
    // Keyboard: Esc leaves the search for the first row, s edits it.
    await page.keyboard.press("Escape");
    await expect(taskRowLink(page, { id: first.id })).toBeFocused();
    await page.keyboard.press("s");
    await pickOption(page, "Erledigt");
    const undo = page
      .locator(".toast", { hasText: "Status: Erledigt" })
      .getByRole("button", { name: "Rückgängig", exact: true });
    await expect(undo).toBeVisible();
    await expect(taskRow(page, first.id)).toHaveCount(0);
    expect(writes).toHaveLength(1);
    expect(writes[0].status).toBe("done");
    expect(preserved(await read())).toEqual(preserved(first));
    await page.screenshot({
      path: testInfo.outputPath(`s1-${surface}-undo.png`),
    });
    await undo.click();
    await expect(taskRow(page, first.id)).toBeVisible();
    expect(writes).toHaveLength(2);
    expect((await read()).revision).toBe(first.revision + 2);
    expect(preserved(await read())).toEqual(preserved(first));

    // Bulk: x checks two rows, "Erledigt" completes both, undo reopens both.
    await page.keyboard.press("k");
    await page.keyboard.press("x");
    await page.keyboard.press("j");
    await page.keyboard.press("x");
    const bulk = page.getByRole("region", { name: "Auswahl" });
    await expect(bulk).toContainText("2 ausgewählt");
    await bulk.getByRole("button", { name: "Erledigt", exact: true }).click();
    await expect(
      page.getByText("2 Aufgaben erledigt.", { exact: true }),
    ).toBeVisible();
    await expect(taskRows(page)).toHaveCount(10);
    await page
      .locator(".toast", { hasText: "2 Aufgaben erledigt." })
      .getByRole("button", { name: "Rückgängig", exact: true })
      .click();
    await expect(taskRows(page)).toHaveCount(12);
    expect(writes).toHaveLength(4);
    expect((await read()).status).toBe("open");

    // Complete once more for the conflict below.
    await page.keyboard.press("Escape");
    await taskRowLink(page, { id: first.id }).focus();
    await page.keyboard.press("s");
    await pickOption(page, "Erledigt");
    await expect(taskRow(page, first.id)).toHaveCount(0);
    const completed = await read();
    expect(completed.status).toBe("done");
    expect(completed.revision).toBe(first.revision + 5);
    expect(writes).toHaveLength(5);
    // The owner's list now holds this revision of the done task.
    await showTaskView(page, "Erledigt");
    const stale = taskRowLink(page, { id: first.id });
    await expect(stale).toContainText(completed.title);
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
    await expect(taskRows(readerPage)).toHaveCount(11);
    await expect(
      readerPage.getByRole("button", { name: /^Aufgabe anlegen/ }),
    ).toHaveCount(0);
    await expect(
      readerPage.getByRole("form", { name: "Aufgabe schnell erfassen" }),
    ).toHaveCount(0);
    // A reader gets no edit menus: the server would refuse anyway.
    await readerPage.keyboard.press("j");
    await readerPage.keyboard.press("s");
    await expect(
      readerPage.getByText("Status lässt sich hier nicht ändern.", {
        exact: true,
      }),
    ).toBeVisible();
    const lowerLink = taskRowLink(readerPage, { id: originals[11].id });
    await lowerLink.focus();
    await readerPage.keyboard.press("Enter");
    const readerDetail = taskPane(readerPage, originals[11].id);
    await expect(readerDetail).toBeVisible();
    await expect(readerDetail.getByText("Nur lesen.")).toBeVisible();
    await expect(readerDetail.locator("form.task-editor")).toHaveCount(0);
    await expect(readerDetail.locator(".task-structure")).toHaveCount(0);
    await readerPage.keyboard.press("Escape");
    await expect(readerDetail).toHaveCount(0);
    await expect(lowerLink).toBeFocused();
    await readerPage.goto(
      `${baseURL}/${surface}/tasks/${list.id}?view=all&open=${first.id}`,
    );
    await expect(taskPane(readerPage, first.id)).toBeVisible();
    await expect(
      readerPage.getByRole("button", { name: "Speichern", exact: true }),
    ).toHaveCount(0);
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
    // The owner's list still holds the old revision: the edit is refused,
    // reported, and the list reloads the current state.
    await expect(stale).not.toContainText("inzwischen geändert");
    const conflict = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/tasks/${first.id}`) &&
        response.status() === 409,
    );
    await stale.focus();
    await page.keyboard.press("s");
    await pickOption(page, "Offen");
    await conflict;
    await expect(
      page.getByText("Status wurde nicht geändert.", { exact: true }),
    ).toBeVisible();
    await expect(stale).toContainText("inzwischen geändert");
    expect(await read()).toEqual(changed);
    await taskSearch(page).fill("kein passender Titel");
    await expect(
      page.getByText("Keine Aufgaben passen zu dieser Ansicht", {
        exact: true,
      }),
    ).toBeVisible();
    const revocation = await context.request.put(membershipPath, {
      headers,
      data: {
        userId: secondIdentity.userId,
        access: null,
        expectedRevision: 3,
        idempotencyKey: randomUUID(),
      },
    });
    expect(revocation.ok()).toBe(true);
    await readerPage.goto(
      `${baseURL}/${surface}/tasks/${list.id}?task=${first.id}`,
    );
    await expect(
      readerPage.getByText(
        surface === "app"
          ? "Diese Liste ist nicht verfügbar oder du hast keinen Zugriff mehr."
          : "Diese Liste ist nicht verfügbar oder Sie haben keinen Zugriff mehr.",
        { exact: true },
      ),
    ).toBeVisible();
    await expect(taskPane(readerPage)).toHaveCount(0);
    const deniedDirectRead = await second.request.get(
      `${baseURL}/api/v1/tasks/${first.id}`,
    );
    expect(deniedDirectRead.status()).toBe(404);
    await second.close();
    await context.close();
  });
}
