import {
  useInfiniteQuery,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  CalendarDays,
  CircleCheck,
  CircleDot,
  Flag,
  FolderOpen,
  Layers,
  List,
  ListChecks,
  Sun,
  Tag,
  Timer,
  UserRound,
  Users,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  ApiError,
  type Assignee,
  type MovePlacement,
  type MoveTask,
  type PersonalPlan,
  type TaskSummary,
} from "@leonaid/api-client";
import {
  Avatar,
  Button,
  ErrorState,
  fullBleedPage,
  Icon,
  IconButton,
  ListView,
  StatusIcon,
  StatusLabel,
  StatusMessage,
  statusShape,
  useOptionalToast,
  type ListColumns,
  type ListProperty,
  type ListSort,
  type ListState,
  type ListViewDefinition,
} from "@leonaid/ui";

import { consumeCreateRequest } from "../command-palette/create-request";
import { useContextCommands } from "../command-palette/store";
import type { ModulePageContext } from "../modules";
import { says, type Address } from "./task-copy";
import { TaskDetail, type TaskMoveControls } from "./task-detail";
import type { Task } from "./task-editor";
import {
  buildTaskRows,
  DUE_BUCKETS,
  DUE_LABELS,
  formatShortDay,
  localIsoDate,
  migrateLegacyTaskQuery,
  PLAN_BUCKETS,
  PLAN_LABELS,
  PLANNED_BUCKETS,
  planLabel,
  relativeDay,
  STATUS_LABELS,
  type TaskRow,
} from "./task-model";
import { TaskOrderHandle, TaskOrdering } from "./task-ordering";
import { TaskQuickAdd, type QuickAddList } from "./task-quick-add";
import { TaskListAccess, TaskListNavigation } from "./task-tools";
import "./tasks.css";

const PAGE_SIZE = 100;
/** Pages loaded without asking (10 × 100 tasks); "Weitere laden" adds more. */
const AUTO_PAGES = 10;

interface Page<T> {
  readonly items: readonly T[];
  readonly nextOffset: number | null;
  readonly orderRevision?: number | null;
}

/** Loads every page of a server list, up to a limit the person can raise. */
function useAllPages<T>(
  queryKey: readonly unknown[],
  fetchPage: (offset: number) => Promise<Page<T>>,
  enabled = true,
) {
  const [limit, setLimit] = useState(AUTO_PAGES);
  const query = useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam }) => fetchPage(pageParam),
    initialPageParam: 0,
    getNextPageParam: (last: Page<T>) => last.nextOffset ?? undefined,
    enabled,
    retry: false,
  });
  const pages = query.data?.pages;
  const count = pages?.length ?? 0;
  const { fetchNextPage, hasNextPage, isError, isFetchingNextPage } = query;
  useEffect(() => {
    if (hasNextPage && !isFetchingNextPage && !isError && count < limit) {
      void fetchNextPage();
    }
  }, [count, fetchNextPage, hasNextPage, isError, isFetchingNextPage, limit]);
  const items = useMemo(
    () => pages?.flatMap((page) => page.items) ?? [],
    [pages],
  );
  return {
    query,
    items,
    orderRevision: pages?.[0]?.orderRevision ?? null,
    /** No data yet, or still loading the pages it loads by itself. */
    loading:
      enabled &&
      (query.isPending || (!!hasNextPage && count < limit && !isError)),
    failed: query.isError && !query.data,
    truncated: !!hasNextPage && count >= limit,
    more: () => setLimit((current) => current + AUTO_PAGES),
  };
}

const compare = (a: number, b: number) => (a === b ? 0 : a < b ? -1 : 1);
const dueTime = (row: TaskRow) =>
  row.task.dueAt ? Date.parse(row.task.dueAt) : Number.POSITIVE_INFINITY;
const byDue = (a: TaskRow, b: TaskRow) => compare(dueTime(a), dueTime(b));
const byPriority = (a: TaskRow, b: TaskRow) =>
  Number(b.task.priority === "high") - Number(a.task.priority === "high");
const byTitle = (a: TaskRow, b: TaskRow) =>
  a.task.title.localeCompare(b.task.title, "de");

/** Runs writes in parallel; rejects with the first failure, after all settled. */
async function settleAll<T>(jobs: readonly Promise<T>[]): Promise<T[]> {
  const results = await Promise.allSettled(jobs);
  const failure = results.find((result) => result.status === "rejected");
  if (failure) throw (failure as PromiseRejectedResult).reason;
  return results.flatMap((result) =>
    result.status === "fulfilled" ? [result.value] : [],
  );
}

type TaskFields = Pick<
  TaskSummary,
  | "id"
  | "title"
  | "description"
  | "epicId"
  | "assigneeUserId"
  | "dueAt"
  | "deferredUntil"
  | "revision"
  | "status"
  | "priority"
  | "tags"
  | "checklist"
>;

/** Both shells (admin rail, PWA) mount the HotkeyProvider the list needs. */
export function TasksPage(
  props: ModulePageContext & {
    basePath: string;
    listId?: string;
    surface?: "web" | "pwa";
  },
) {
  // Old bookmarks and search links become list view parameters before the
  // list reads the URL: a layout effect, then the first real render.
  const [migrated, setMigrated] = useState(false);
  useLayoutEffect(() => {
    const next = migrateLegacyTaskQuery(window.location.search, {
      listId: props.listId,
      userId: props.identity.userId,
    });
    if (next !== null) {
      window.history.replaceState(
        window.history.state,
        "",
        `${window.location.pathname}${next}${window.location.hash}`,
      );
    }
    setMigrated(true);
  }, [props.identity.userId, props.listId]);
  return migrated ? <TasksWorkspace {...props} /> : null;
}

function TasksWorkspace({
  basePath,
  client,
  identity,
  listId,
  surface,
}: ModulePageContext & {
  basePath: string;
  listId?: string;
  surface?: "web" | "pwa";
}) {
  const address: Address =
    (surface ?? (basePath.startsWith("/app") ? "pwa" : "web")) === "pwa"
      ? "du"
      : "Sie";
  const cache = useQueryClient();
  const toast = useOptionalToast();
  // Consumed in an effect: StrictMode calls state initialisers twice, and
  // the second call would find the parameter already gone.
  const [createRequested, setCreateRequested] = useState(false);
  useEffect(() => {
    if (consumeCreateRequest("task")) setCreateRequested(true);
  }, []);

  const selected = useQuery({
    queryKey: ["task-list", listId],
    queryFn: () => client.getTaskList(listId!),
    enabled: !!listId,
    retry: false,
  });
  const editableLists = useQuery({
    queryKey: ["task-lists", "editable"],
    queryFn: () => client.listTaskLists({ limit: 100 }),
    enabled: !listId,
    retry: false,
  });
  const quickLists = useMemo<QuickAddList[]>(
    () =>
      (editableLists.data?.items ?? [])
        .filter((list) => list.canEdit)
        .map((list) => ({ id: list.id, title: list.title })),
    [editableLists.data],
  );

  /* ----- server sources ----- */
  const [listState, setListState] = useState<ListState | null>(null);
  const statusFilter = listState?.filters.find(
    (filter) => filter.prop === "status",
  );
  const needsDone =
    listState !== null &&
    (!statusFilter || statusFilter.values.includes("done"));
  // Once loaded, done tasks stay: switching views back and forth is instant.
  const [doneWanted, setDoneWanted] = useState(false);
  useEffect(() => {
    if (needsDone) setDoneWanted(true);
  }, [needsDone]);
  const timeZone = useRef(
    Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  ).current;
  const open = useAllPages(["tasks", "open", listId ?? null], (offset) =>
    client.listTasks({
      listId,
      status: "open",
      deferredState: "all",
      sort: listId ? "manual" : "created",
      offset,
      limit: PAGE_SIZE,
    }),
  );
  const done = useAllPages(
    ["tasks", "done", listId ?? null],
    (offset) =>
      client.listTasks({
        listId,
        status: "done",
        deferredState: "all",
        sort: "created",
        offset,
        limit: PAGE_SIZE,
      }),
    doneWanted,
  );
  const planFor = (view: "today" | "planned" | "someday") => (offset: number) =>
    client.listTaskPlans({ view, timeZone, offset, limit: PAGE_SIZE });
  const plansToday = useAllPages(["tasks", "plans", "today"], planFor("today"));
  const plansPlanned = useAllPages(
    ["tasks", "plans", "planned"],
    planFor("planned"),
  );
  const plansSomeday = useAllPages(
    ["tasks", "plans", "someday"],
    planFor("someday"),
  );
  const plans = useMemo(
    () => [...plansToday.items, ...plansPlanned.items, ...plansSomeday.items],
    [plansToday.items, plansPlanned.items, plansSomeday.items],
  );
  const rows = useMemo(
    () =>
      buildTaskRows({
        open: open.items,
        done: doneWanted ? done.items : [],
        plans,
        listId,
        now: new Date(),
      }),
    [open.items, done.items, doneWanted, plans, listId],
  );
  const rowById = useMemo(
    () => new Map(rows.map((row) => [row.id, row])),
    [rows],
  );
  const rowsRef = useRef(rowById);
  rowsRef.current = rowById;
  /**
   * Reloads the sources an edit can change: the task lists (open and done)
   * and/or my plans. A plan edit leaves the task lists alone; a task edit
   * reloads the plans only when it can move a task in or out of them.
   */
  const refresh = useCallback(
    (
      scope: { tasks?: boolean; plans?: boolean } = {
        tasks: true,
        plans: true,
      },
    ) =>
      Promise.all([
        ...(scope.tasks
          ? [
              cache.invalidateQueries({ queryKey: ["tasks", "open"] }),
              cache.invalidateQueries({ queryKey: ["tasks", "done"] }),
            ]
          : []),
        ...(scope.plans
          ? [
              cache.invalidateQueries({ queryKey: ["tasks", "plans"] }),
              cache.invalidateQueries({ queryKey: ["task-plan"] }),
            ]
          : []),
      ]),
    [cache],
  );

  /* ----- people I may assign, per list ----- */
  const editableListIds = useMemo(
    () =>
      [
        ...new Set(
          rows.filter((row) => row.task.canEdit).map((row) => row.task.listId),
        ),
      ].sort(),
    [rows],
  );
  const assigneeResults = useQueries({
    queries: editableListIds.map((id) => ({
      queryKey: ["task-assignees", id, "all"],
      queryFn: () => client.listTaskAssignees(id, { limit: 100 }),
      retry: false,
      staleTime: 300_000,
    })),
  });
  const assigneeSignature = assigneeResults
    .map((result) => result.dataUpdatedAt)
    .join(",");
  const assignable = useMemo(
    () =>
      new Map(
        editableListIds.map((id, index) => [
          id,
          assigneeResults[index]?.data?.items as
            | readonly Assignee[]
            | undefined,
        ]),
      ),
    // The results array is new on every render; its data changes are not.
    [editableListIds, assigneeSignature],
  );
  const assignableRef = useRef(assignable);
  assignableRef.current = assignable;

  /* ----- edits ----- */
  const updateFields = useCallback(
    (
      task: TaskFields,
      patch: Partial<Pick<TaskFields, "status" | "assigneeUserId">>,
    ) =>
      client.updateTask(task.id, {
        title: task.title,
        description: task.description ?? "",
        epicId: task.epicId ?? null,
        assigneeUserId:
          patch.assigneeUserId !== undefined
            ? patch.assigneeUserId
            : (task.assigneeUserId ?? null),
        dueAt: task.dueAt ?? null,
        deferredUntil: task.deferredUntil ?? null,
        expectedRevision: task.revision,
        status: patch.status ?? task.status,
        idempotencyKey: crypto.randomUUID(),
      }),
    [client],
  );
  const setPriority = useCallback(
    (task: TaskFields, priority: "high" | "none") =>
      client.setTaskStructure(task.id, {
        idempotencyKey: crypto.randomUUID(),
        expectedRevision: task.revision,
        priority,
        tagIds: task.tags.map((tag) => tag.id),
        checklist: task.checklist,
      }),
    [client],
  );
  /**
   * Writes each row, refreshes what changed, and offers an undo of the
   * writes that were saved. All failed: rejects (the list reports it). Some
   * failed: reports "k von n" itself, with the undo, and resolves
   * "cancelled" so the list adds no second toast.
   */
  const editRows = useCallback(
    async <S,>(
      ids: readonly string[],
      write: (row: TaskRow) => Promise<S> | null,
      revert: (saved: S, row: TaskRow) => Promise<unknown>,
      scope: { tasks?: boolean; plans?: boolean } = {
        tasks: true,
        plans: true,
      },
    ): Promise<{ undo: () => Promise<void> } | "cancelled"> => {
      const targets = ids.flatMap((id) => {
        const row = rowsRef.current.get(id);
        return row ? [row] : [];
      });
      const pairs: { row: TaskRow; job: Promise<S> }[] = targets.flatMap(
        (row) => {
          const job = write(row);
          return job ? [{ row, job }] : [];
        },
      );
      try {
        const results = await Promise.allSettled(pairs.map((pair) => pair.job));
        const saved = results.flatMap((result, index) =>
          result.status === "fulfilled"
            ? [{ value: result.value, row: pairs[index]!.row }]
            : [],
        );
        const undo = async () => {
          try {
            await settleAll(saved.map(({ value, row }) => revert(value, row)));
          } finally {
            await refresh(scope);
          }
        };
        const failure = results.find((result) => result.status === "rejected");
        if (!failure) return { undo };
        if (saved.length === 0) throw (failure as PromiseRejectedResult).reason;
        toast?.show({
          title: `${saved.length} von ${pairs.length} Aufgaben geändert.`,
          description: says(
            address,
            "Die übrigen wurden nicht gespeichert; die Liste zeigt den aktuellen Stand. Versuche es für sie erneut.",
            "Die übrigen wurden nicht gespeichert; die Liste zeigt den aktuellen Stand. Versuchen Sie es für sie erneut.",
          ),
          tone: "error",
          action: {
            label: "Rückgängig",
            run: () => {
              undo().catch(() =>
                toast?.show({
                  title: "Die Änderung wurde nicht zurückgesetzt.",
                  tone: "error",
                }),
              );
            },
          },
        });
        return "cancelled";
      } finally {
        await refresh(scope);
      }
    },
    [address, refresh, toast],
  );
  const setStatus = useCallback(
    (ids: readonly string[], status: "open" | "done") =>
      editRows<Task>(
        ids,
        (row) =>
          row.task.status === status
            ? null
            : updateFields(row.task, { status }),
        (saved, row) => updateFields(saved, { status: row.task.status }),
      ),
    [editRows, updateFields],
  );
  const planTo = useCallback(
    async (
      row: TaskRow,
      state: PersonalPlan["state"],
      plannedOn: string | null,
      current?: PersonalPlan,
    ) => {
      const before = current ?? row.plan ?? (await client.getTaskPlan(row.id));
      const saved = await client.setTaskPlan(row.id, {
        idempotencyKey: crypto.randomUUID(),
        expectedRevision: before.revision,
        state,
        plannedOn,
      });
      return { before, saved };
    },
    [client],
  );

  /* ----- properties ----- */
  const people = useMemo(() => {
    const names = new Map<string, string>([
      [identity.userId, identity.displayName],
    ]);
    for (const row of rows) {
      if (row.task.assigneeUserId && row.task.assigneeName) {
        names.set(row.task.assigneeUserId, row.task.assigneeName);
      }
    }
    for (const list of assignable.values()) {
      for (const person of list ?? []) {
        names.set(person.userId, person.displayName);
      }
    }
    const [self, ...others] = [...names.entries()];
    return [self!, ...others.sort(([, a], [, b]) => a.localeCompare(b, "de"))];
  }, [assignable, identity.displayName, identity.userId, rows]);
  const lists = useMemo(() => {
    const titles = new Map<string, string>();
    for (const row of rows) titles.set(row.task.listId, row.task.listTitle);
    return [...titles.entries()].sort(([, a], [, b]) =>
      a.localeCompare(b, "de"),
    );
  }, [rows]);
  const epics = useMemo(() => {
    const titles = new Map<string, string>();
    for (const row of [...rows].sort((a, b) => a.listIndex - b.listIndex)) {
      if (row.task.epicId) {
        titles.set(row.task.epicId, row.task.epicTitle ?? "Abschnitt");
      }
    }
    return [...titles.entries()];
  }, [rows]);
  const tags = useMemo(() => {
    const titles = new Map<string, string>();
    for (const row of rows) {
      for (const tag of row.task.tags) titles.set(tag.id, tag.title);
    }
    return [...titles.entries()].sort(([, a], [, b]) =>
      a.localeCompare(b, "de"),
    );
  }, [rows]);
  const today = localIsoDate();

  const properties = useMemo<ListProperty<TaskRow>[]>(() => {
    const allEditable = (targets: readonly TaskRow[]) =>
      targets.every((row) => row.task.canEdit);
    const statusOptions = (["open", "done"] as const).map((value) => ({
      value,
      label: STATUS_LABELS[value],
      icon: (
        <StatusIcon
          label={STATUS_LABELS[value]}
          status={statusShape[STATUS_LABELS[value]] ?? "open"}
        />
      ),
    }));
    const personOption = ([userId, name]: readonly [string, string]) => ({
      value: userId,
      label: userId === identity.userId ? `${name} (ich)` : name,
      icon: <Avatar name={name} size="xs" />,
    });
    const nobody = { value: "none", label: "Niemand" };
    const planEditValues = new Set(["today", "someday", "none"]);
    const planOptions = PLAN_BUCKETS.map((value) => ({
      value,
      label: PLAN_LABELS[value],
    }));
    return [
      {
        id: "status",
        label: "Status",
        icon: CircleDot,
        get: (row) => row.task.status,
        options: statusOptions,
        edit: {
          key: "s",
          options: (targets) => (allEditable(targets) ? statusOptions : []),
          apply: (ids, value) => setStatus(ids, value as "open" | "done"),
        },
        chip: (row) => <StatusLabel status={STATUS_LABELS[row.task.status]} />,
      },
      {
        id: "plan",
        label: "Plan",
        icon: Sun,
        get: (row) => row.planBucket,
        options: planOptions,
        edit: {
          key: "w",
          options: (targets) =>
            targets.every((row) => row.task.status === "open")
              ? planOptions.filter((option) => planEditValues.has(option.value))
              : [],
          apply: (ids, value) =>
            editRows(
              ids,
              (row) =>
                planTo(
                  row,
                  value === "today"
                    ? "scheduled"
                    : value === "someday"
                      ? "someday"
                      : "unplanned",
                  value === "today" ? localIsoDate() : null,
                ),
              ({ before, saved }, row) =>
                planTo(row, before.state, before.plannedOn, saved),
              { plans: true },
            ),
        },
      },
      {
        id: "due",
        label: "Fällig",
        icon: CalendarDays,
        get: (row) => row.dueBucket,
        options: DUE_BUCKETS.map((value) => ({
          value,
          label: DUE_LABELS[value],
        })),
        chip: (row) =>
          row.task.dueAt ? (
            <span
              className={
                row.dueBucket === "overdue"
                  ? "task-due task-overdue"
                  : "task-due"
              }
            >
              <CalendarDays aria-hidden="true" size={13} />
              {relativeDay(localIsoDate(new Date(row.task.dueAt)), today)}
              {row.dueBucket === "overdue" ? (
                <span className="sr-only"> (überfällig)</span>
              ) : null}
            </span>
          ) : null,
      },
      {
        id: "assignee",
        label: "Zuständig",
        icon: UserRound,
        get: (row) => row.task.assigneeUserId ?? "none",
        options: [...people.map(personOption), nobody],
        edit: {
          key: "a",
          options: (targets) => {
            if (!allEditable(targets) || targets.length === 0) return [];
            const sets = targets.map((row) =>
              assignableRef.current.get(row.task.listId),
            );
            if (sets.some((set) => !set)) return [];
            const [first, ...rest] = sets as (readonly Assignee[])[];
            return [
              ...first!
                .filter((person) =>
                  rest.every((set) =>
                    set.some((other) => other.userId === person.userId),
                  ),
                )
                .map((person) =>
                  personOption([person.userId, person.displayName] as const),
                ),
              nobody,
            ];
          },
          apply: (ids, value) =>
            editRows<Task>(
              ids,
              (row) =>
                (row.task.assigneeUserId ?? "none") === value
                  ? null
                  : updateFields(row.task, {
                      assigneeUserId: value === "none" ? null : value,
                    }),
              (saved, row) =>
                updateFields(saved, {
                  assigneeUserId: row.task.assigneeUserId ?? null,
                }),
            ),
        },
        chip: (row) =>
          row.task.assigneeUserId ? (
            <>
              <Avatar
                label={`Zuständig: ${row.task.assigneeName ?? "unbekannt"}`}
                name={row.task.assigneeName ?? "?"}
                size="xs"
              />
              <span className="chip-name">{row.task.assigneeName}</span>
            </>
          ) : (
            <>
              <span
                aria-label="Niemand zuständig"
                className="avatar-empty"
                role="img"
              />
              <span className="chip-name">Niemand</span>
            </>
          ),
      },
      ...(listId
        ? [
            {
              id: "epic",
              label: "Abschnitt",
              icon: Layers,
              get: (row: TaskRow) => row.task.epicId ?? "none",
              options: [
                ...epics.map(([value, label]) => ({ value, label })),
                { value: "none", label: "Ohne Abschnitt" },
              ],
            },
          ]
        : [
            {
              id: "list",
              label: "Liste",
              icon: List,
              get: (row: TaskRow) => row.task.listId,
              options: lists.map(([value, label]) => ({ value, label })),
            },
          ]),
      {
        id: "priority",
        label: "Priorität",
        icon: Flag,
        get: (row) => (row.task.priority === "high" ? "high" : "none"),
        options: [
          { value: "high", label: "Hoch" },
          { value: "none", label: "Normal" },
        ],
        groupable: false,
        edit: {
          key: "p",
          options: (targets) =>
            allEditable(targets)
              ? [
                  { value: "high", label: "Hoch" },
                  { value: "none", label: "Normal" },
                ]
              : [],
          apply: (ids, value) =>
            editRows<Task>(
              ids,
              (row) =>
                row.task.priority === value
                  ? null
                  : setPriority(row.task, value as "high" | "none"),
              (saved, row) => setPriority(saved, row.task.priority),
              { tasks: true },
            ),
        },
      },
      {
        id: "tag",
        label: "Schlagwort",
        icon: Tag,
        get: (row) => row.task.tags.map((tag) => tag.id),
        options: tags.map(([value, label]) => ({ value, label })),
        groupable: false,
      },
      {
        id: "deferral",
        label: "Wiedervorlage",
        icon: Timer,
        get: (row) => (row.deferred ? "deferred" : "active"),
        options: [
          { value: "active", label: "Aktiv" },
          { value: "deferred", label: "Zurückgestellt" },
        ],
        groupable: false,
      },
    ];
  }, [
    editRows,
    epics,
    identity.userId,
    listId,
    lists,
    people,
    planTo,
    setPriority,
    setStatus,
    tags,
    today,
    updateFields,
  ]);
  const propertyById = useMemo(
    () => new Map(properties.map((prop) => [prop.id, prop])),
    [properties],
  );

  const sorts = useMemo<ListSort<TaskRow>[]>(
    () => [
      ...(listId
        ? [
            {
              id: "manual",
              label: "Reihenfolge",
              compare: (a: TaskRow, b: TaskRow) => a.listIndex - b.listIndex,
            },
          ]
        : []),
      {
        id: "due",
        label: "Fälligkeit",
        compare: (a, b) =>
          byDue(a, b) || byPriority(a, b) || a.listIndex - b.listIndex,
      },
      ...(listId
        ? []
        : [
            {
              id: "plan",
              label: "Planung",
              compare: (a: TaskRow, b: TaskRow) =>
                compare(a.planIndex, b.planIndex) ||
                byDue(a, b) ||
                a.listIndex - b.listIndex,
            },
          ]),
      {
        id: "priority",
        label: "Priorität",
        compare: (a, b) => byPriority(a, b) || byDue(a, b),
      },
      { id: "title", label: "Titel A–Z", compare: byTitle },
      {
        id: "created",
        label: "Neueste zuerst",
        compare: (a, b) => b.task.createdAt.localeCompare(a.task.createdAt),
      },
    ],
    [listId],
  );

  const views = useMemo<ListViewDefinition[]>(() => {
    const openActive = [
      { prop: "status", values: ["open"] },
      { prop: "deferral", values: ["active"] },
    ];
    const mine = { prop: "assignee", values: [identity.userId] };
    return listId
      ? [
          {
            id: "open",
            label: "Offen",
            filters: openActive,
            groupBy: "epic",
            sort: "manual",
          },
          {
            id: "mine",
            label: "Für mich",
            filters: [mine, ...openActive],
            groupBy: "epic",
            sort: "manual",
          },
          {
            id: "all",
            label: "Alle",
            filters: [],
            groupBy: "status",
            sort: "manual",
          },
          {
            id: "done",
            label: "Erledigt",
            filters: [{ prop: "status", values: ["done"] }],
            groupBy: null,
            sort: "title",
          },
        ]
      : [
          {
            id: "plan",
            label: "Mein Plan",
            filters: [{ prop: "plan", values: [...PLANNED_BUCKETS] }],
            groupBy: "plan",
            sort: "plan",
          },
          {
            id: "mine",
            label: "Für mich",
            filters: [mine, ...openActive],
            groupBy: "due",
            sort: "due",
          },
          {
            id: "open",
            label: "Alle offenen",
            filters: openActive,
            groupBy: "due",
            sort: "due",
          },
          {
            id: "lists",
            label: "Nach Liste",
            filters: [],
            groupBy: "list",
            sort: "due",
          },
          {
            id: "done",
            label: "Erledigt",
            filters: [{ prop: "status", values: ["done"] }],
            groupBy: null,
            sort: "title",
          },
        ];
  }, [identity.userId, listId]);

  const searchText = useCallback(
    (row: TaskRow) =>
      [
        row.task.title,
        ...row.task.tags.map((tag) => tag.title),
        row.task.assigneeName ?? "",
        row.task.listTitle,
        row.task.epicTitle ?? "",
      ].join(" "),
    [],
  );

  /* ----- ordering ----- */
  const moveKind: "list" | "plan" | null = listState
    ? listId
      ? listState.sort === "manual" &&
        (listState.groupBy === null || listState.groupBy === "epic") &&
        !!selected.data?.canEdit
        ? "list"
        : null
      : listState.sort === "plan" &&
          (listState.groupBy === null || listState.groupBy === "plan")
        ? "plan"
        : null
    : null;
  const canMove = useCallback(
    (row: TaskRow) =>
      moveKind === "list"
        ? row.task.canEdit && row.task.status === "open"
        : moveKind === "plan"
          ? !!row.plan &&
            row.plan.state !== "unplanned" &&
            row.planBucket !== "due"
          : false,
    [moveKind],
  );
  /* Movable rows in the order the list shows them (server order). */
  const movable = useMemo(() => {
    if (!moveKind || !listState) return [];
    const needle = listState.query.trim().toLowerCase();
    return rows
      .filter(
        (row) =>
          canMove(row) &&
          listState.filters.every((filter) => {
            const prop = propertyById.get(filter.prop);
            if (!prop || filter.values.length === 0) return true;
            const value = prop.get(row);
            return (typeof value === "string" ? [value] : value).some((item) =>
              filter.values.includes(item),
            );
          }) &&
          (!needle || searchText(row).toLowerCase().includes(needle)),
      )
      .sort((a, b) =>
        moveKind === "list"
          ? a.listIndex - b.listIndex
          : compare(a.planIndex, b.planIndex),
      );
  }, [canMove, listState, moveKind, propertyById, rows, searchText]);
  const movableIds = useMemo(() => movable.map((row) => row.id), [movable]);
  const movableSet = useMemo(() => new Set(movableIds), [movableIds]);
  const [moveMessage, setMoveMessage] = useState("");
  const reorder = useMutation({
    mutationFn: (attempt: { row: TaskRow; body: MoveTask }) =>
      client.moveTask(attempt.row.id, attempt.body),
    onSuccess: async (_result, attempt) => {
      setMoveMessage(`Aufgabe „${attempt.row.task.title}“ wurde verschoben.`);
      await Promise.all([
        refresh(),
        ...(listId
          ? [cache.invalidateQueries({ queryKey: ["task-list", listId] })]
          : []),
      ]);
      requestAnimationFrame(() => {
        const active = document.activeElement;
        const handle = document.getElementById(`task-move-${attempt.row.id}`);
        if (
          handle &&
          (active === document.body || active === null || active === handle)
        ) {
          handle.focus();
        }
      });
    },
  });
  const submitMove = (
    row: TaskRow,
    placement: MovePlacement,
    options: {
      target?: TaskRow;
      targetEpicId?: string | null;
      targetDate?: string;
    } = {},
  ) => {
    if (reorder.isPending) return;
    const personal = moveKind === "plan";
    const revision = personal ? plansToday.orderRevision : open.orderRevision;
    if (revision == null || (personal && !row.plan)) return;
    setMoveMessage(`Aufgabe „${row.task.title}“ wird verschoben.`);
    reorder.mutate({
      row,
      body: personal
        ? {
            context: "personal",
            expectedOrderRevision: revision,
            expectedPlanRevision: row.plan!.revision,
            idempotencyKey: crypto.randomUUID(),
            placement,
            targetDate:
              options.targetDate ??
              options.target?.plan?.plannedOn ??
              row.plan?.plannedOn ??
              undefined,
          }
        : {
            context: "list",
            expectedOrderRevision: revision,
            expectedTaskRevision: row.task.revision,
            idempotencyKey: crypto.randomUUID(),
            placement,
            targetEpicId:
              options.targetEpicId !== undefined
                ? options.targetEpicId
                : (options.target?.task.epicId ?? row.task.epicId ?? null),
          },
    });
  };
  const reloadOrder = async () => {
    await Promise.all([refresh(), ...(listId ? [selected.refetch()] : [])]);
    reorder.reset();
    setMoveMessage("Reihenfolge neu geladen.");
  };
  const moveControls = (row: TaskRow): TaskMoveControls | null => {
    if (!moveKind || !movableSet.has(row.id)) return null;
    const index = movableIds.indexOf(row.id);
    const previous = movable[index - 1] ?? null;
    const next = movable[index + 1] ?? null;
    return {
      kind: moveKind,
      previous,
      next,
      pending: reorder.isPending || !!reorder.error,
      up: () =>
        previous &&
        submitMove(row, { before: previous.id }, { target: previous }),
      down: () => next && submitMove(row, { after: next.id }, { target: next }),
      toEpic: (epicId) =>
        submitMove(row, { edge: "end" }, { targetEpicId: epicId }),
      toDay: (plannedOn) =>
        submitMove(row, { edge: "end" }, { targetDate: plannedOn }),
    };
  };

  /* ----- row anatomy ----- */
  const handlesDisabled = reorder.isPending || !!reorder.error;
  const columns = useMemo<ListColumns<TaskRow>>(
    () => ({
      leading: (row) => (
        <span className="task-leading">
          {movableSet.has(row.id) ? (
            <TaskOrderHandle
              disabled={handlesDisabled}
              id={row.id}
              title={row.task.title}
            />
          ) : movableSet.size > 0 ? (
            <span aria-hidden="true" className="task-handle-space" />
          ) : null}
          {row.task.priority === "high" ? (
            <Icon
              className="flag-high"
              icon={Flag}
              label="Hohe Priorität"
              size={14}
            />
          ) : (
            <span aria-hidden="true" className="flag-space" />
          )}
        </span>
      ),
      primary: (row) => (
        <span
          className={row.task.status === "done" ? "is-struck" : undefined}
          data-task-row={row.id}
        >
          {row.task.title}
        </span>
      ),
      secondary: (row) => {
        const steps = row.task.checklist.length
          ? `${row.task.checklist.filter((step) => step.done).length}/${row.task.checklist.length} Schritte`
          : null;
        return [
          listId ? row.task.epicTitle : row.task.listTitle,
          steps,
          row.task.tags.length
            ? row.task.tags.map((tag) => `#${tag.title}`).join(" ")
            : null,
          row.deferred && row.task.deferredUntil
            ? `zurückgestellt bis ${formatShortDay(row.task.deferredUntil)}`
            : null,
        ]
          .filter(Boolean)
          .join(" · ");
      },
      trailing: (row) => {
        const label = planLabel(row, today);
        return label ? (
          <span className="task-plan">{label}</span>
        ) : (
          <span className="subtle">–</span>
        );
      },
    }),
    [handlesDisabled, listId, movableSet, today],
  );
  const getId = useCallback((row: TaskRow) => row.id, []);
  const detailTitle = useCallback((row: TaskRow) => row.task.title, []);

  /* ----- create ----- */
  const [adding, setAdding] = useState(false);
  // All tasks: the quick add opens even before a list exists and then
  // points to "Neue Liste".
  const mayCreate = listId ? !!selected.data?.canEdit : true;
  const startAdding = useCallback(() => {
    setAdding(true);
    window.setTimeout(
      () => document.getElementById("quick-add-input")?.focus(),
      0,
    );
  }, []);
  const [tool, setTool] = useState<"lists" | "access" | null>(null);
  const handledCreate = useRef(false);
  useEffect(() => {
    if (!createRequested || handledCreate.current) return;
    if (mayCreate) {
      handledCreate.current = true;
      startAdding();
    } else if (listId && selected.isSuccess) {
      handledCreate.current = true;
      toast?.show({
        title: says(
          address,
          "In dieser Liste darfst du keine Aufgaben anlegen.",
          "In dieser Liste dürfen Sie keine Aufgaben anlegen.",
        ),
        tone: "info",
      });
    }
  }, [
    address,
    createRequested,
    listId,
    mayCreate,
    selected.isSuccess,
    startAdding,
    toast,
  ]);
  const listFilter = listState?.filters.find(
    (filter) => filter.prop === "list",
  );
  const assigneeFilter = listState?.filters.find(
    (filter) => filter.prop === "assignee",
  );

  /* ----- bulk ----- */
  const [completing, setCompleting] = useState(false);
  const completeChecked = async (ids: readonly string[], clear: () => void) => {
    if (completing) return;
    // Only open rows are written; done ones are skipped and not counted.
    const changed = ids.filter(
      (id) => rowsRef.current.get(id)?.task.status === "open",
    ).length;
    setCompleting(true);
    try {
      const result = await setStatus(ids, "done");
      // A partial result has reported itself (k von n, with undo).
      if (result === "cancelled") {
        clear();
        return;
      }
      toast?.show({
        title:
          changed === 1
            ? "1 Aufgabe erledigt."
            : `${changed} Aufgaben erledigt.`,
        tone: "success",
        action: {
          label: "Rückgängig",
          run: () => {
            result.undo().catch(() =>
              toast?.show({
                title: "Status wurde nicht zurückgesetzt.",
                tone: "error",
              }),
            );
          },
        },
      });
      clear();
    } catch {
      toast?.show({
        title: "Die Aufgaben wurden nicht erledigt.",
        description: says(
          address,
          "Die Liste zeigt den aktuellen Stand. Versuche es erneut.",
          "Die Liste zeigt den aktuellen Stand. Versuchen Sie es erneut.",
        ),
        tone: "error",
      });
    } finally {
      setCompleting(false);
    }
  };

  /* ----- render ----- */
  const listUnavailable =
    !!listId &&
    selected.error instanceof ApiError &&
    [403, 404].includes(selected.error.status);
  if (listUnavailable) {
    return (
      <div className="tasks-page" data-zone="tasks">
        <ErrorState title="Aufgabenliste nicht verfügbar">
          <p>
            {says(
              address,
              "Diese Liste ist nicht verfügbar oder du hast keinen Zugriff mehr.",
              "Diese Liste ist nicht verfügbar oder Sie haben keinen Zugriff mehr.",
            )}
          </p>
          <p>
            <a href={basePath}>Alle zugänglichen Aufgaben</a>
          </p>
        </ErrorState>
      </div>
    );
  }

  const onlyDone =
    !!statusFilter &&
    statusFilter.values.length === 1 &&
    statusFilter.values[0] === "done";
  const failed =
    open.failed ||
    plansToday.failed ||
    plansPlanned.failed ||
    plansSomeday.failed ||
    (onlyDone && done.failed) ||
    (!!listId && selected.isError);
  const loading =
    open.loading ||
    plansToday.loading ||
    plansPlanned.loading ||
    plansSomeday.loading ||
    (!!listId && selected.isPending) ||
    (onlyDone && done.loading);
  const truncated = [open, done, plansToday, plansPlanned, plansSomeday].filter(
    (source) => source.truncated,
  );
  const status = failed ? "error" : loading ? "loading" : "ready";

  const tools: ReactNode = (
    <>
      <IconButton
        aria-controls="task-list-navigation"
        aria-expanded={tool === "lists"}
        icon={FolderOpen}
        label="Liste wechseln"
        onClick={() =>
          setTool((current) => (current === "lists" ? null : "lists"))
        }
      />
      {selected.data?.canEdit ? (
        <IconButton
          aria-controls="task-list-access"
          aria-expanded={tool === "access"}
          icon={Users}
          label="Zugriff verwalten"
          onClick={() =>
            setTool((current) => (current === "access" ? null : "access"))
          }
        />
      ) : null}
      {adding && mayCreate ? (
        <TaskQuickAdd
          address={address}
          assignSelf={
            listState?.viewId === "mine" ||
            (!listId && listState?.viewId === "plan") ||
            !!assigneeFilter?.values.includes(identity.userId)
          }
          client={client}
          defaultListId={
            listFilter?.values.length === 1 ? listFilter.values[0]! : null
          }
          fixedList={
            listId && selected.data
              ? { id: selected.data.id, title: selected.data.title }
              : null
          }
          identity={identity}
          lists={quickLists}
          onClose={() => setAdding(false)}
          onNeedList={() => setTool("lists")}
          planToday={!listId && listState?.viewId === "plan"}
        />
      ) : null}
    </>
  );

  const beforeList: ReactNode = (
    <>
      {tool === "lists" ? (
        <TaskListNavigation
          address={address}
          basePath={basePath}
          client={client}
          listId={listId}
          onClose={() => setTool(null)}
        />
      ) : null}
      {tool === "access" && selected.data?.canEdit ? (
        <TaskListAccess
          client={client}
          list={selected.data}
          onClose={() => setTool(null)}
        />
      ) : null}
      {reorder.error ? (
        <StatusMessage tone="error">
          <p>
            {reorder.error instanceof ApiError && reorder.error.status === 409
              ? says(
                  address,
                  "Die Reihenfolge wurde inzwischen geändert. Lade sie neu; die Bewegung wurde nicht übernommen.",
                  "Die Reihenfolge wurde inzwischen geändert. Laden Sie sie neu; die Bewegung wurde nicht übernommen.",
                )
              : reorder.error instanceof ApiError &&
                  [401, 403, 404].includes(reorder.error.status)
                ? says(
                    address,
                    "Du darfst diese Reihenfolge nicht mehr ändern. Lade die Aufgaben neu.",
                    "Sie dürfen diese Reihenfolge nicht mehr ändern. Laden Sie die Aufgaben neu.",
                  )
                : says(
                    address,
                    "Der Speicherstatus der Bewegung ist unklar. Wiederhole denselben Vorgang oder lade die Reihenfolge neu.",
                    "Der Speicherstatus der Bewegung ist unklar. Wiederholen Sie denselben Vorgang oder laden Sie die Reihenfolge neu.",
                  )}
          </p>
          <div className="cluster">
            {!(
              reorder.error instanceof ApiError &&
              [401, 403, 404, 409].includes(reorder.error.status)
            ) && reorder.variables ? (
              <Button
                disabled={reorder.isPending}
                onClick={() => reorder.mutate(reorder.variables!)}
                size="sm"
                variant="secondary"
              >
                Erneut versuchen
              </Button>
            ) : null}
            <Button
              disabled={reorder.isPending}
              id="task-order-reload"
              onClick={() => void reloadOrder()}
              size="sm"
              variant="secondary"
            >
              Neu laden
            </Button>
          </div>
        </StatusMessage>
      ) : null}
      {status === "ready" && needsDone && done.loading ? (
        <p className="small subtle task-note" role="status">
          Erledigte Aufgaben werden geladen …
        </p>
      ) : null}
      {status === "ready" && needsDone && done.failed ? (
        // Mixed views still show the open tasks; say that the done ones
        // and the count are missing instead of failing silently.
        <StatusMessage tone="error">
          <p>
            Erledigte Aufgaben konnten nicht geladen werden. Die Liste zeigt nur
            offene Aufgaben.
          </p>
          <Button
            loading={done.query.isFetching}
            onClick={() => void done.query.refetch()}
            size="sm"
            variant="secondary"
          >
            Erledigte erneut laden
          </Button>
        </StatusMessage>
      ) : null}
      {status === "ready" && truncated.length > 0 ? (
        <StatusMessage tone="info">
          <p>
            Es sind noch nicht alle Aufgaben geladen. Filter und Suche beziehen
            sich auf die geladenen.
          </p>
          <Button
            onClick={() => truncated.forEach((source) => source.more())}
            size="sm"
            variant="secondary"
          >
            Weitere Aufgaben laden
          </Button>
        </StatusMessage>
      ) : null}
      <p aria-live="polite" className="sr-only" role="status">
        {moveMessage}
      </p>
    </>
  );

  return (
    // The list fills the shell's main edge to edge; it has its own gutters.
    <div className="tasks-page" data-zone="tasks" {...fullBleedPage}>
      <TaskOrdering
        ids={movableIds}
        onCancel={() => setMoveMessage("Verschieben abgebrochen.")}
        onMove={(id, targetId, side) => {
          const row = rowById.get(id);
          const target = rowById.get(targetId);
          if (!row || !target) return;
          submitMove(
            row,
            side === "before" ? { before: targetId } : { after: targetId },
            { target },
          );
        }}
      >
        <ListView<TaskRow>
          address={address}
          beforeList={beforeList}
          bulkActions={(ids, clear) => {
            const targets = ids.flatMap((id) => {
              const row = rowById.get(id);
              return row ? [row] : [];
            });
            return (
              <Button
                disabled={
                  !targets.every((row) => row.task.canEdit) ||
                  targets.every((row) => row.task.status === "done")
                }
                icon={CircleCheck}
                loading={completing}
                onClick={() => void completeChecked(ids, clear)}
                size="sm"
                variant="secondary"
              >
                Erledigt
              </Button>
            );
          }}
          className="tasks-list"
          columns={columns}
          createCommandId="create:task"
          createLabel="Aufgabe anlegen"
          detailTitle={detailTitle}
          emptyIcon={ListChecks}
          entityLabel={{ one: "Aufgabe", many: "Aufgaben" }}
          getId={getId}
          headerExtra={tools}
          id={listId ? "task-list" : "tasks"}
          onCreate={mayCreate ? startAdding : undefined}
          onRetry={() => {
            void refresh();
            if (listId) void selected.refetch();
          }}
          onStateChange={setListState}
          properties={properties}
          renderDetail={(row, pane) => (
            <TaskDetail
              address={address}
              basePath={basePath}
              client={client}
              close={pane.close}
              key={row.id}
              listPage={!!listId}
              move={moveControls(row)}
              row={row}
              userId={identity.userId}
            />
          )}
          rows={rows}
          searchText={searchText}
          sorts={sorts}
          status={status}
          title={
            listId ? (selected.data?.title ?? "Aufgabenliste") : "Aufgaben"
          }
          useCommands={useContextCommands}
          views={views}
        />
      </TaskOrdering>
    </div>
  );
}
