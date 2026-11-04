import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Fragment, StrictMode } from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import type {
  CurrentIdentityResponse,
  LeonAidApiClient,
  PlannedTask,
  TaskSummary,
} from "@leonaid/api-client";
import { resetCommandPaletteState } from "@leonaid/features";
import { HotkeyProvider, ToastProvider } from "@leonaid/ui";

import {
  buildTaskRows,
  dueBucket,
  localIsoDate,
  migrateLegacyTaskQuery,
  planBucket,
} from "../../../packages/features/src/tasks/task-model";
import { TasksPage } from "../../../packages/features/src/tasks/tasks";
import { installDialogPolyfill } from "../../../packages/ui/src/test-utils/dialog-polyfill";

const me = "00000000-0000-4000-8000-0000000000aa";
const listA = "10000000-0000-4000-8000-000000000001";

beforeAll(() => {
  installDialogPolyfill();
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  Element.prototype.scrollIntoView ??= () => {};
  window.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
});

afterEach(() => {
  resetCommandPaletteState();
  window.history.replaceState(null, "", "/admin/tasks");
  vi.restoreAllMocks();
});

function task(
  id: string,
  title: string,
  overrides: Partial<TaskSummary> = {},
): TaskSummary {
  return {
    actionTitle: null,
    assigneeName: null,
    assigneeUserId: null,
    canEdit: true,
    checklist: [],
    createdAt: "2026-10-01T10:00:00Z",
    createdBy: me,
    deferredUntil: null,
    description: "",
    dueAt: null,
    epicId: null,
    epicTitle: null,
    id,
    listId: listA,
    listTitle: "Adventsmarkt",
    priority: "none",
    revision: 1,
    status: "open",
    tags: [],
    title,
    updatedAt: "2026-10-01T10:00:00Z",
    ...overrides,
  };
}

function planned(
  base: TaskSummary,
  plan: PlannedTask["personalPlan"],
  planSource: PlannedTask["planSource"] = "planned",
): PlannedTask {
  return { ...base, personalPlan: plan, planSource };
}

const identity = {
  userId: me,
  displayName: "Klara Admin",
  globalRoles: [],
  actionMemberships: [],
  navigation: [],
} as unknown as CurrentIdentityResponse;

function harness({
  open = [],
  done = [],
  today = [],
  later = [],
  someday = [],
}: {
  open?: TaskSummary[];
  done?: TaskSummary[];
  today?: PlannedTask[];
  later?: PlannedTask[];
  someday?: PlannedTask[];
}) {
  const client = {
    listTasks: vi.fn(async (query: { status?: string }) => ({
      items: query.status === "done" ? done : open,
      nextOffset: null,
      orderRevision: 3,
    })),
    listTaskPlans: vi.fn(async (query: { view: string }) => ({
      items:
        query.view === "today"
          ? today
          : query.view === "planned"
            ? later
            : someday,
      nextOffset: null,
      orderRevision: 7,
    })),
    listTaskLists: vi.fn(async () => ({
      items: [
        {
          id: listA,
          title: "Adventsmarkt",
          canEdit: true,
          actionId: null,
          orderRevision: 3,
          ownerUserId: me,
          revision: 1,
        },
      ],
      nextOffset: null,
    })),
    getTaskList: vi.fn(async () => ({
      id: listA,
      title: "Adventsmarkt",
      canEdit: true,
      actionId: null,
      orderRevision: 3,
      ownerUserId: me,
      revision: 1,
    })),
    listTaskAssignees: vi.fn(async () => ({
      items: [{ userId: me, displayName: "Klara Admin" }],
      nextOffset: null,
    })),
    updateTask: vi.fn(
      async (id: string, body: { status: string; expectedRevision: number }) =>
        ({
          ...task(id, "x"),
          status: body.status,
          revision: body.expectedRevision + 1,
        }) as TaskSummary,
    ),
    createTask: vi.fn(async (_list: string, body: { title: string }) =>
      task("new", body.title),
    ),
    setTaskPlan: vi.fn(async (id: string) => ({
      taskId: id,
      state: "scheduled",
      plannedOn: localIsoDate(),
      revision: 1,
    })),
    getTaskPlan: vi.fn(async (id: string) => ({
      taskId: id,
      state: "unplanned",
      plannedOn: null,
      revision: 0,
    })),
    listTaskTags: vi.fn(async () => ({ items: [], nextOffset: null })),
    listTaskEpics: vi.fn(async () => ({ items: [], nextOffset: null })),
    listTaskListMembers: vi.fn(async () => ({
      items: [],
      nextOffset: null,
      ownerUserId: me,
      revision: 1,
    })),
    listTaskActionContexts: vi.fn(async () => ({
      items: [],
      nextOffset: null,
    })),
  };
  return client;
}

function renderPage(
  client: ReturnType<typeof harness>,
  {
    path = "/admin/tasks",
    listId,
    surface = "web",
    strict = false,
  }: {
    path?: string;
    listId?: string;
    surface?: "web" | "pwa";
    strict?: boolean;
  } = {},
) {
  window.history.replaceState(null, "", path);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const Wrapper = strict ? StrictMode : Fragment;
  return render(
    <Wrapper>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <HotkeyProvider>
            <TasksPage
              basePath={surface === "web" ? "/admin/tasks" : "/app/tasks"}
              client={client as unknown as LeonAidApiClient}
              identity={identity}
              listId={listId}
              surface={surface}
            />
          </HotkeyProvider>
        </ToastProvider>
      </QueryClientProvider>
    </Wrapper>,
  );
}

function press(key: string) {
  act(() => {
    (document.activeElement ?? document.body).dispatchEvent(
      new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }),
    );
  });
}

describe("task model", () => {
  it("rewrites old task URLs to list view parameters", () => {
    expect(
      migrateLegacyTaskQuery("?scope=all&view=due-today&sort=due&search=S3", {
        listId: listA,
        userId: me,
      }),
    ).toBe("?view=open&f.status=open&f.due=today&sort=due&group=none&q=S3");
    expect(
      migrateLegacyTaskQuery("?scope=mine&view=plan-planned", {
        userId: me,
      }),
    ).toBe("?view=plan&f.plan=week&f.plan=later");
    expect(
      migrateLegacyTaskQuery("?task=t1", { listId: listA, userId: me }),
    ).toBe("?view=all&open=t1");
    expect(
      migrateLegacyTaskQuery("?scope=mine&view=open&sort=created", {
        userId: me,
      }),
    ).toBe("?view=mine&sort=created&group=none");
    expect(
      migrateLegacyTaskQuery("?scope=all&view=deferred", {
        listId: listA,
        userId: me,
      }),
    ).toBe("?view=open&f.status=open&f.deferral=deferred");
    // New URLs stay as they are.
    expect(migrateLegacyTaskQuery("?view=done&q=x", { userId: me })).toBeNull();
  });

  it("files plans into buckets the way the server's views do", () => {
    const today = "2026-11-03";
    const plan = (plannedOn: string | null, state = "scheduled") => ({
      taskId: "t",
      state: state as "scheduled",
      plannedOn,
      revision: 1,
    });
    expect(planBucket(plan("2026-11-01"), "planned", today)).toBe("today");
    expect(planBucket(plan("2026-11-04"), "planned", today)).toBe("week");
    expect(planBucket(plan("2026-11-20"), "planned", today)).toBe("later");
    expect(planBucket(plan(null, "someday"), "planned", today)).toBe("someday");
    expect(planBucket(null, "due", today)).toBe("due");
    expect(planBucket(null, null, today)).toBe("none");
  });

  it("buckets due dates by local day and keeps done tasks out of overdue", () => {
    const now = new Date(2026, 10, 3, 9);
    const at = (day: number) => new Date(2026, 10, day, 12).toISOString();
    expect(dueBucket(task("a", "a", { dueAt: at(2) }), now)).toBe("overdue");
    expect(
      dueBucket(task("a", "a", { dueAt: at(2), status: "done" }), now),
    ).toBe("past");
    expect(dueBucket(task("a", "a", { dueAt: at(3) }), now)).toBe("today");
    expect(dueBucket(task("a", "a", { dueAt: at(10) }), now)).toBe("week");
    expect(dueBucket(task("a", "a", { dueAt: at(11) }), now)).toBe("later");
  });

  it("merges plans into list rows and adds planned tasks of other lists only on the all page", () => {
    const now = new Date(2026, 10, 3, 9);
    const a = task("a", "A");
    const b = task("b", "B", { listId: "other" });
    const plans = [
      planned(a, {
        taskId: "a",
        state: "scheduled",
        plannedOn: "2026-11-03",
        revision: 2,
      }),
      planned(b, {
        taskId: "b",
        state: "someday",
        plannedOn: null,
        revision: 1,
      }),
    ];
    const all = buildTaskRows({ open: [a], done: [], plans, now });
    expect(all.map((row) => [row.id, row.planBucket, row.planIndex])).toEqual([
      ["a", "today", 0],
      ["b", "someday", 1],
    ]);
    expect("personalPlan" in all[1]!.task).toBe(false);
    const list = buildTaskRows({
      open: [a],
      done: [],
      plans,
      listId: listA,
      now,
    });
    expect(list.map((row) => row.id)).toEqual(["a"]);
  });
});

describe("tasks page", () => {
  it("opens on Mein Plan, grouped by plan, and switches views", async () => {
    const a = task("a", "Stände aufbauen");
    const b = task("b", "Kasse zählen");
    const client = harness({
      open: [a, b],
      today: [
        planned(a, {
          taskId: "a",
          state: "scheduled",
          plannedOn: localIsoDate(),
          revision: 1,
        }),
      ],
    });
    renderPage(client);
    expect(await screen.findByText("Stände aufbauen")).toBeTruthy();
    expect(screen.queryByText("Kasse zählen")).toBeNull();
    expect(
      screen.getByRole("button", { name: /^Heute/, expanded: true }),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Alle offenen" }));
    expect(await screen.findByText("Kasse zählen")).toBeTruthy();
    expect(window.location.search).toBe("?view=open");
  });

  it("changes the status with s and undoes it from the toast", async () => {
    const client = harness({ open: [task("a", "Stände aufbauen")] });
    renderPage(client, { path: "/admin/tasks?view=open" });
    await screen.findByText("Stände aufbauen");
    press("j");
    press("s");
    fireEvent.click(await screen.findByRole("option", { name: /Erledigt/ }));
    await act(async () => {});
    expect(client.updateTask).toHaveBeenLastCalledWith(
      "a",
      expect.objectContaining({ status: "done", expectedRevision: 1 }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Rückgängig" }));
    await act(async () => {});
    expect(client.updateTask).toHaveBeenLastCalledWith(
      "a",
      expect.objectContaining({ status: "open", expectedRevision: 2 }),
    );
  });

  it("reports a partial bulk edit with an undo for the saved rows", async () => {
    const client = harness({
      open: [task("a", "Stände aufbauen"), task("b", "Kasse zählen")],
    });
    const { ApiError } = await import("@leonaid/api-client");
    client.updateTask.mockImplementation(async (id, body) => {
      if (id === "b") throw new ApiError(409, { message: "conflict" } as never);
      return {
        ...task(id, "x"),
        status: body.status,
        revision: body.expectedRevision + 1,
      } as TaskSummary;
    });
    renderPage(client, { path: "/admin/tasks?view=open&sort=title" });
    await screen.findByText("Stände aufbauen");
    press("j");
    press("x");
    press("j");
    press("x");
    press("s");
    fireEvent.click(await screen.findByRole("option", { name: /Erledigt/ }));
    expect(await screen.findByText("1 von 2 Aufgaben geändert.")).toBeTruthy();
    expect(screen.queryByText("Status wurde nicht geändert.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Rückgängig" }));
    await act(async () => {});
    expect(client.updateTask).toHaveBeenLastCalledWith(
      "a",
      expect.objectContaining({ status: "open", expectedRevision: 2 }),
    );
  });

  it("hides who sees the list when nobody else does", async () => {
    const client = harness({ open: [task("a", "Stände aufbauen")] });
    renderPage(client, { path: "/admin/tasks?view=open&open=a" });
    await screen.findByRole("complementary", { name: /Stände/ });
    await act(async () => {});
    expect(client.listTaskListMembers).toHaveBeenCalled();
    expect(screen.queryByText("Wer die Liste sieht")).toBeNull();
  });

  it("refuses edits on tasks the person may only read", async () => {
    const client = harness({
      open: [task("a", "Nur lesen", { canEdit: false })],
    });
    renderPage(client, { path: "/admin/tasks?view=open" });
    await screen.findByText("Nur lesen");
    press("j");
    press("s");
    expect(
      await screen.findByText("Status lässt sich hier nicht ändern."),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("link", { name: /Nur lesen/ }));
    const pane = screen.getByRole("complementary", { name: /Nur lesen/ });
    expect(within(pane).getByText("Nur lesen.")).toBeTruthy();
    expect(
      within(pane).queryByRole("form", { name: "Aufgabe bearbeiten" }),
    ).toBeNull();
    expect(
      within(pane).getByRole("heading", { name: "Persönliche Planung" }),
    ).toBeTruthy();
  });

  it("quick add creates in the chosen list and plans it for today in Mein Plan", async () => {
    const client = harness({});
    renderPage(client);
    await screen.findByText("Noch keine Aufgaben");
    // Header button and the empty state offer it.
    expect(
      await screen.findAllByRole("button", { name: /^Aufgabe anlegen/ }),
    ).toHaveLength(2);
    press("c");
    const field = await screen.findByPlaceholderText(
      "Neue Aufgabe – Enter legt an, Esc bricht ab",
    );
    await act(async () => {});
    expect(
      (screen.getByLabelText("Aufgabenliste") as HTMLSelectElement).value,
    ).toBe(listA);
    fireEvent.change(field, { target: { value: "Glühwein bestellen" } });
    fireEvent.submit(field.closest("form")!);
    await act(async () => {});
    await act(async () => {});
    expect(client.createTask).toHaveBeenCalledWith(
      listA,
      expect.objectContaining({
        title: "Glühwein bestellen",
        assigneeUserId: me,
      }),
    );
    expect(client.setTaskPlan).toHaveBeenCalledWith(
      "new",
      expect.objectContaining({
        state: "scheduled",
        plannedOn: localIsoDate(),
      }),
    );
    expect(
      await screen.findByText(
        "Aufgabe „Glühwein bestellen“ angelegt – im Plan unter Heute.",
      ),
    ).toBeTruthy();
  });

  it("opens the quick add for the palette's create request", async () => {
    const client = harness({});
    renderPage(client, { path: "/admin/tasks?create=task", strict: true });
    const field = await screen.findByRole("textbox", { name: "Titel" });
    await act(async () => {});
    expect(document.activeElement).toBe(field);
    expect(window.location.search).not.toContain("create");
  });

  it("asks before a draft in the pane is dropped", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const client = harness({ open: [task("a", "Stände aufbauen")] });
    renderPage(client, { path: `/admin/tasks/${listA}`, listId: listA });
    fireEvent.click(
      await screen.findByRole("link", { name: /Stände aufbauen/ }),
    );
    const editor = await screen.findByRole("form", {
      name: "Aufgabe bearbeiten",
    });
    fireEvent.change(within(editor).getByLabelText("Beschreibung"), {
      target: { value: "Entwurf" },
    });
    act(() => {
      document.body.focus();
    });
    press("Escape");
    expect(confirm).toHaveBeenCalledWith(
      "Ihre Änderungen wurden noch nicht gespeichert. Entwurf verwerfen?",
    );
    expect(screen.getByRole("complementary", { name: /Stände/ })).toBeTruthy();
    confirm.mockReturnValue(true);
    press("Escape");
    await act(async () => {});
    expect(screen.queryByRole("complementary", { name: /Stände/ })).toBeNull();
  });

  it("speaks with Du in the app and maps old links", async () => {
    const client = harness({ open: [task("a", "Stände aufbauen")] });
    renderPage(client, {
      path: `/app/tasks/${listA}?scope=all&view=open&search=zzz`,
      listId: listA,
      surface: "pwa",
    });
    // "Offen" is the default view, so only the search stays.
    expect(window.location.search).toBe("?q=zzz");
    expect(
      await screen.findByText(
        "Entferne einen Filter oder ändere den Suchbegriff.",
      ),
    ).toBeTruthy();
  });

  it("shows the unavailable list with the right address", async () => {
    const client = harness({});
    const { ApiError } = await import("@leonaid/api-client");
    client.getTaskList.mockRejectedValue(
      new ApiError(404, { message: "not found" } as never),
    );
    renderPage(client, {
      path: `/app/tasks/${listA}`,
      listId: listA,
      surface: "pwa",
    });
    expect(
      await screen.findByText(
        "Diese Liste ist nicht verfügbar oder du hast keinen Zugriff mehr.",
      ),
    ).toBeTruthy();
  });
});
