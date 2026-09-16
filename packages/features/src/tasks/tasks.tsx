import {
  Add01Icon,
  ArrowDown01Icon,
  ArrowUp01Icon,
  Calendar03Icon,
  DragDropIcon,
  FolderOpenIcon,
  MoreHorizontalIcon,
  UserGroupIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import {
  ApiError,
  type MovePlacement,
  type MoveTask,
  type PlannedTask,
  type TaskSummary,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";
import type { ModulePageContext } from "../modules";
import { ListMembersPanel } from "./list-members";
import { TaskEditor, TaskPlanPanel, type Task } from "./task-editor";
import {
  ActionContextSearch,
  useActionContexts,
} from "../shared/action-contexts";
import "./tasks.css";

function date(value: string) {
  return new Intl.DateTimeFormat("de-DE", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

type TaskView =
  | "open"
  | "due-today"
  | "due-next"
  | "deferred"
  | "done"
  | "plan-today"
  | "plan-planned"
  | "plan-someday";
type TaskScope = "mine" | "all";
type TaskSort = "created" | "due" | "section" | "manual";
type ListedTask = TaskSummary | PlannedTask;
type MoveAttempt = { taskId: string; title: string; body: MoveTask };

const taskViews = new Set<TaskView>([
  "open",
  "due-today",
  "due-next",
  "deferred",
  "done",
  "plan-today",
  "plan-planned",
  "plan-someday",
]);
const taskSorts = new Set<TaskSort>(["created", "due", "section", "manual"]);

function calendarBoundary(daysFromToday: number) {
  const now = new Date();
  return new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate() + daysFromToday,
  ).toISOString();
}

function viewQuery(view: TaskView) {
  switch (view) {
    case "due-today":
      return {
        status: "open" as const,
        deferredState: "all" as const,
        dueFrom: calendarBoundary(0),
        dueBefore: calendarBoundary(1),
      };
    case "due-next":
      return {
        status: "open" as const,
        deferredState: "all" as const,
        dueFrom: calendarBoundary(1),
        dueBefore: calendarBoundary(8),
      };
    case "deferred":
      return {
        status: "open" as const,
        deferredState: "deferred" as const,
      };
    case "done":
      return {
        status: "done" as const,
        deferredState: "all" as const,
      };
    default:
      return {
        status: "open" as const,
        deferredState: "active" as const,
      };
  }
}

function planView(view: TaskView) {
  if (view === "plan-today") return "today" as const;
  if (view === "plan-planned") return "planned" as const;
  if (view === "plan-someday") return "someday" as const;
  return null;
}

function calendarDate(value: string) {
  const [year, month, day] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(
    new Date(year!, month! - 1, day),
  );
}

function isPlannedTask(value: object): value is PlannedTask {
  return "personalPlan" in value && "planSource" in value;
}

function localToday() {
  const now = new Date();
  const part = (value: number) => String(value).padStart(2, "0");
  return `${now.getFullYear()}-${part(now.getMonth() + 1)}-${part(now.getDate())}`;
}

function closeTaskMenu(element: Element) {
  element.closest("details")?.removeAttribute("open");
}

function SortableTaskRow({
  task,
  movable,
  disabled,
  children,
}: {
  task: ListedTask;
  movable: boolean;
  disabled: boolean;
  children: (handle: ReactNode) => ReactNode;
}) {
  const {
    attributes,
    listeners,
    setActivatorNodeRef,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: task.id, disabled: !movable || disabled });
  const handle = movable ? (
    <button
      {...attributes}
      {...listeners}
      ref={setActivatorNodeRef}
      className="task-order-handle"
      id={`task-move-${task.id}`}
      type="button"
      disabled={disabled}
      aria-label={`Aufgabe verschieben: ${task.title}`}
      title="Ziehen oder mit Leertaste und Pfeiltasten verschieben"
    >
      <HugeiconsIcon icon={DragDropIcon} size={18} aria-hidden="true" />
    </button>
  ) : null;
  return (
    <li
      ref={setNodeRef}
      className={`task-row${movable ? " task-row--sortable" : ""}${isDragging ? " task-row--dragging" : ""}`}
      data-task-id={task.id}
      style={{ transform: CSS.Transform.toString(transform), transition }}
    >
      {children(handle)}
    </li>
  );
}

function taskLocation(defaultScope: TaskScope = "mine") {
  const query = new URLSearchParams(window.location.search);
  const view = query.get("view") as TaskView | null;
  const sort = query.get("sort") as TaskSort | null;
  return {
    scope:
      query.get("scope") === "all"
        ? ("all" as const)
        : query.get("scope") === "mine"
          ? ("mine" as const)
          : defaultScope,
    view: view && taskViews.has(view) ? view : ("open" as const),
    sort: sort && taskSorts.has(sort) ? sort : ("created" as const),
    search: query.get("search") ?? "",
    taskId: query.get("task"),
  };
}

function TaskTool({
  label,
  expanded,
  controls,
  onClick,
  icon,
}: {
  label: string;
  expanded: boolean;
  controls: string;
  onClick: () => void;
  icon: typeof FolderOpenIcon;
}) {
  return (
    <span className="task-tool">
      <button
        type="button"
        className="ui-icon-button"
        aria-label={label}
        aria-expanded={expanded}
        aria-controls={controls}
        title={label}
        onClick={onClick}
      >
        <HugeiconsIcon icon={icon} size={20} aria-hidden="true" />
      </button>
      <span role="tooltip">{label}</span>
    </span>
  );
}

function QuickTaskForm({
  client,
  identity,
  list,
  lists,
  scope,
  onCreated,
}: {
  client: ModulePageContext["client"];
  identity: ModulePageContext["identity"];
  list?: { id: string; title: string; canEdit: boolean };
  lists: readonly { id: string; title: string; canEdit: boolean }[];
  scope: TaskScope;
  onCreated: () => Promise<unknown>;
}) {
  const editableLists = lists.filter((candidate) => candidate.canEdit);
  const [listChoice, setListChoice] = useState(list?.id ?? "");
  const [title, setTitle] = useState("");
  const [assignee, setAssignee] = useState("");
  const [assignmentTouched, setAssignmentTouched] = useState(false);
  const operation = useRef(crypto.randomUUID());
  useEffect(() => {
    if (list) setListChoice(list.id);
  }, [list]);
  const assignees = useQuery({
    queryKey: ["task-assignees", "quick", listChoice, identity.displayName],
    queryFn: () =>
      client.listTaskAssignees(listChoice, {
        search: identity.displayName,
        limit: 100,
      }),
    enabled: !!listChoice,
    retry: false,
  });
  useEffect(() => {
    if (assignmentTouched || !assignees.data) return;
    const self = assignees.data.items.some(
      (person) => person.userId === identity.userId,
    );
    setAssignee(scope === "mine" && self ? identity.userId : "");
  }, [assignees.data, assignmentTouched, identity.userId, scope]);
  const create = useMutation({
    mutationFn: () =>
      client.createTask(listChoice, {
        title: title.trim(),
        description: "",
        assigneeUserId: assignee || null,
        epicId: null,
        dueAt: null,
        deferredUntil: null,
        idempotencyKey: operation.current,
      }),
    onSuccess: async () => {
      setTitle("");
      operation.current = crypto.randomUUID();
      await onCreated();
    },
  });
  if (list && !list.canEdit) return null;
  return (
    <form
      className="task-quick-create"
      aria-label="Aufgabe schnell erfassen"
      data-list-scope={list ? "current" : "select"}
      onSubmit={(event) => {
        event.preventDefault();
        if (listChoice && title.trim()) create.mutate();
      }}
    >
      <label className="task-quick-title">
        <span className="sr-only">Titel</span>
        <input
          aria-label="Titel"
          maxLength={240}
          placeholder="Neue Aufgabe …"
          value={title}
          disabled={create.isPending}
          onChange={(event) => {
            setTitle(event.target.value);
            operation.current = crypto.randomUUID();
            create.reset();
          }}
        />
      </label>
      {!list && (
        <label className="task-quick-list">
          <span>Aufgabenliste</span>
          <select
            aria-label="Aufgabenliste"
            value={listChoice}
            disabled={create.isPending}
            onChange={(event) => {
              setListChoice(event.target.value);
              setAssignmentTouched(false);
              setAssignee("");
              operation.current = crypto.randomUUID();
              create.reset();
            }}
          >
            <option value="">Liste wählen …</option>
            {editableLists.map((candidate) => (
              <option key={candidate.id} value={candidate.id}>
                {candidate.title}
              </option>
            ))}
          </select>
        </label>
      )}
      <label className="task-quick-assignee">
        <span>Zuständigkeit</span>
        <select
          aria-label="Zuständigkeit"
          value={assignee}
          disabled={!listChoice || assignees.isPending || create.isPending}
          onChange={(event) => {
            setAssignmentTouched(true);
            setAssignee(event.target.value);
            operation.current = crypto.randomUUID();
            create.reset();
          }}
        >
          <option value="">Nicht zugewiesen</option>
          {assignees.data?.items.map((person) => (
            <option key={person.userId} value={person.userId}>
              {person.displayName}
              {person.userId === identity.userId ? " (ich)" : ""}
            </option>
          ))}
        </select>
      </label>
      <Button
        className="task-quick-submit"
        type="submit"
        disabled={!listChoice || !title.trim() || create.isPending}
        icon={<HugeiconsIcon icon={Add01Icon} size={18} aria-hidden="true" />}
      >
        {create.isPending ? "Wird angelegt …" : "Neue Aufgabe"}
      </Button>
      {create.error && (
        <StatusMessage tone="error">
          Die Aufgabe konnte nicht angelegt werden. Der Titel bleibt erhalten.
        </StatusMessage>
      )}
    </form>
  );
}

export function TasksPage({
  client,
  identity,
  basePath,
  listId,
}: ModulePageContext & { basePath: string; listId?: string }) {
  const cache = useQueryClient();
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, {
      activationConstraint: { delay: 220, tolerance: 6 },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );
  const initialLocation = useRef(taskLocation(listId ? "all" : "mine")).current;
  const initialPersonalView = !listId && !!planView(initialLocation.view);
  const [navigationOpen, setNavigationOpen] = useState(false);
  const [accessOpen, setAccessOpen] = useState(false);
  const [detailTaskId, setDetailTaskId] = useState(initialLocation.taskId);
  const targetId = detailTaskId;
  const target = useQuery({
    queryKey: ["tasks", "detail", identity.userId, targetId],
    queryFn: () => client.getTask(targetId!),
    enabled: !!targetId,
    retry: false,
    // Keep the revision used to open this editor until the draft is closed.
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    gcTime: 0,
  });
  const targetList = useQuery({
    queryKey: ["task-list", target.data?.listId],
    queryFn: () => client.getTaskList(target.data!.listId),
    enabled: !!target.data,
    retry: false,
  });
  const [editingCanEdit, setEditingCanEdit] = useState(false);
  const [editing, setEditing] = useState<Task | "new" | null>(null);
  const editorDirty = useRef(false);
  const closingDetail = useRef(false);
  const detailUrl = useRef(window.location.href);
  const pendingReturn = useRef<{ scrollY: number; focusId: string } | null>(
    null,
  );
  const editorTrigger = useRef<HTMLButtonElement | null>(null);
  const [forMe, setForMe] = useState(
    initialPersonalView || initialLocation.scope === "mine",
  );
  const [search, setSearch] = useState(
    initialPersonalView ? "" : initialLocation.search,
  );
  const [listOffset, setListOffset] = useState(0);
  const [status, setStatus] = useState<TaskView>(
    listId && planView(initialLocation.view) ? "open" : initialLocation.view,
  );
  const [sort, setSort] = useState<TaskSort>(
    initialPersonalView
      ? "manual"
      : !listId && ["section", "manual"].includes(initialLocation.sort)
        ? "created"
        : initialLocation.sort,
  );
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(
    () => new Set(),
  );
  const [title, setTitle] = useState("");
  const [newListActionId, setNewListActionId] = useState("");
  const [listActionFilter, setListActionFilter] = useState("");
  const contexts = useActionContexts(client);
  const { knownActions, managedActions } = contexts;
  const operation = useRef(crypto.randomUUID());
  const lists = useQuery({
    queryKey: ["task-lists", listOffset, listActionFilter],
    queryFn: () =>
      client.listTaskLists({
        offset: listOffset,
        actionId: listActionFilter || undefined,
      }),
  });
  const selected = useQuery({
    queryKey: ["task-list", listId],
    queryFn: () => client.getTaskList(listId!),
    enabled: !!listId,
  });
  const epics = useQuery({
    queryKey: ["task-epics", listId, "ordering"],
    queryFn: () => client.listTaskEpics(listId!, { limit: 100 }),
    enabled: !!listId && sort === "manual" && !!selected.data?.canEdit,
    retry: false,
  });
  const updateUrl = (
    values: Partial<{
      scope: TaskScope;
      view: TaskView;
      sort: TaskSort;
      search: string;
      taskId: string | null;
    }>,
    mode: "push" | "replace" = "replace",
  ) => {
    const url = new URL(window.location.href);
    const nextScope = values.scope ?? (forMe ? "mine" : "all");
    const nextView = values.view ?? status;
    const nextSort = values.sort ?? sort;
    const nextSearch = values.search ?? search;
    const nextTask = values.taskId === undefined ? detailTaskId : values.taskId;
    url.searchParams.set("scope", nextScope);
    url.searchParams.set("view", nextView);
    url.searchParams.set("sort", nextSort);
    if (nextSearch) url.searchParams.set("search", nextSearch);
    else url.searchParams.delete("search");
    if (nextTask) url.searchParams.set("task", nextTask);
    else url.searchParams.delete("task");
    window.history[`${mode}State`](window.history.state, "", url);
    detailUrl.current = url.href;
  };
  const restoreListPosition = () => {
    const target = pendingReturn.current;
    pendingReturn.current = null;
    requestAnimationFrame(() => {
      if (target) {
        window.scrollTo({ top: target.scrollY });
        document.getElementById(target.focusId)?.focus();
      } else if (editorTrigger.current?.isConnected) {
        editorTrigger.current.focus();
      } else {
        document.getElementById("tasks-heading")?.focus();
      }
    });
  };
  const discardDraft = () =>
    closingDetail.current ||
    !editorDirty.current ||
    window.confirm(
      "Deine Änderungen wurden noch nicht gespeichert. Entwurf verwerfen?",
    );
  const closeEditor = (force = false) => {
    if (!force && !discardDraft()) return;
    closingDetail.current = true;
    editorDirty.current = false;
    setEditing(null);
    if (!detailTaskId) {
      restoreListPosition();
      return;
    }
    if (window.history.state?.tasksDetail) {
      window.history.back();
      return;
    }
    updateUrl({ taskId: null });
    setDetailTaskId(null);
    closingDetail.current = false;
    restoreListPosition();
  };
  useEffect(() => {
    const back = (event: PopStateEvent) => {
      if (!discardDraft()) {
        window.history.pushState(
          { ...(window.history.state ?? {}), tasksDetail: true },
          "",
          detailUrl.current,
        );
        return;
      }
      closingDetail.current = false;
      editorDirty.current = false;
      const location = taskLocation(listId ? "all" : "mine");
      const view = listId && planView(location.view) ? "open" : location.view;
      const personal = !listId && !!planView(view);
      setForMe(personal || location.scope === "mine");
      setStatus(view);
      setSort(
        personal
          ? "manual"
          : !listId && ["section", "manual"].includes(location.sort)
            ? "created"
            : location.sort,
      );
      setSearch(personal ? "" : location.search);
      setDetailTaskId(location.taskId);
      setEditing(null);
      const returnState = event.state?.tasksReturn;
      if (returnState) pendingReturn.current = returnState;
      if (!location.taskId) restoreListPosition();
    };
    window.addEventListener("popstate", back);
    return () => window.removeEventListener("popstate", back);
  });
  const openTask = (
    task: Task,
    canEdit: boolean,
    trigger: HTMLButtonElement,
  ) => {
    editorTrigger.current = trigger;
    const focusId = trigger.id || `task-open-${task.id}`;
    trigger.id = focusId;
    const returnState = { scrollY: window.scrollY, focusId };
    window.history.replaceState(
      { ...(window.history.state ?? {}), tasksReturn: returnState },
      "",
      window.location.href,
    );
    const url = new URL(window.location.href);
    url.searchParams.set("task", task.id);
    window.history.pushState({ tasksDetail: true }, "", url);
    detailUrl.current = url.href;
    setEditingCanEdit(canEdit);
    setEditing(task);
    setDetailTaskId(task.id);
  };
  const personalView = planView(status);
  const timeZone = useRef(
    Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  ).current;
  const tasks = useInfiniteQuery({
    queryKey: ["tasks", listId, forMe, search, status, sort],
    queryFn: ({ pageParam }) =>
      personalView
        ? client.listTaskPlans({
            view: personalView,
            timeZone,
            offset: pageParam,
            limit: 50,
          })
        : client.listTasks({
            listId,
            forMe,
            search,
            offset: pageParam,
            limit: 50,
            sort,
            ...viewQuery(status),
          }),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => lastPage.nextOffset ?? undefined,
    retry: false,
  });
  const taskItems = tasks.data?.pages.flatMap((page) => page.items) ?? [];
  const orderRevision = tasks.data?.pages[0]?.orderRevision;
  const canMove = (task: ListedTask) =>
    personalView
      ? isPlannedTask(task) && task.personalPlan !== null
      : !!listId && sort === "manual" && task.canEdit;
  const movableTasks = taskItems.filter(canMove);
  const movableTaskIds = movableTasks.map((task) => task.id);
  const [moveMessage, setMoveMessage] = useState("");
  const moveFocus = useRef<string | null>(null);
  const reorder = useMutation({
    mutationFn: (attempt: MoveAttempt) =>
      client.moveTask(attempt.taskId, attempt.body),
    onSuccess: async (_result, attempt) => {
      setMoveMessage(`Aufgabe „${attempt.title}“ wurde verschoben.`);
      await Promise.all([
        cache.invalidateQueries({ queryKey: ["tasks"] }),
        ...(listId
          ? [cache.invalidateQueries({ queryKey: ["task-list", listId] })]
          : []),
      ]);
      requestAnimationFrame(() => {
        (
          document.getElementById(`task-move-${moveFocus.current}`) ??
          document.getElementById("tasks-heading")
        )?.focus();
        moveFocus.current = null;
      });
    },
  });
  const submitMove = (
    task: ListedTask,
    placement: MovePlacement,
    options: {
      target?: ListedTask;
      targetEpicId?: string | null;
      targetDate?: string;
    } = {},
  ) => {
    if (orderRevision == null || !canMove(task)) return;
    const plan = isPlannedTask(task) ? task.personalPlan : null;
    const targetPlan =
      options.target && isPlannedTask(options.target)
        ? options.target.personalPlan
        : null;
    moveFocus.current = task.id;
    setMoveMessage(`Aufgabe „${task.title}“ wird verschoben.`);
    reorder.mutate({
      taskId: task.id,
      title: task.title,
      body: personalView
        ? {
            context: "personal",
            expectedOrderRevision: orderRevision,
            expectedPlanRevision: plan!.revision,
            idempotencyKey: crypto.randomUUID(),
            placement,
            targetDate:
              options.targetDate ?? targetPlan?.plannedOn ?? plan?.plannedOn,
          }
        : {
            context: "list",
            expectedOrderRevision: orderRevision,
            expectedTaskRevision: task.revision,
            idempotencyKey: crypto.randomUUID(),
            placement,
            targetEpicId:
              options.targetEpicId !== undefined
                ? options.targetEpicId
                : (options.target?.epicId ?? task.epicId ?? null),
          },
    });
  };
  const finishDrag = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id || reorder.isPending) return;
    const from = movableTaskIds.indexOf(String(active.id));
    const to = movableTaskIds.indexOf(String(over.id));
    if (from < 0 || to < 0) return;
    submitMove(
      movableTasks[from]!,
      from < to ? { after: String(over.id) } : { before: String(over.id) },
      { target: movableTasks[to] },
    );
  };
  const reloadOrder = async () => {
    const taskId = moveFocus.current;
    await Promise.all([
      tasks.refetch(),
      ...(listId ? [selected.refetch()] : []),
    ]);
    reorder.reset();
    setMoveMessage("Reihenfolge neu geladen.");
    requestAnimationFrame(() => {
      (
        document.getElementById(`task-move-${taskId}`) ??
        document.getElementById("tasks-heading")
      )?.focus();
      moveFocus.current = null;
    });
  };
  const create = useMutation({
    mutationFn: () =>
      client.createTaskList({
        title: title.trim(),
        actionId: newListActionId || null,
        idempotencyKey: operation.current,
      }),
    onSuccess: (list) => window.location.assign(`${basePath}/${list.id}`),
  });
  type StatusAttempt = {
    task: Task;
    status: "open" | "done";
    idempotencyKey: string;
    undo: boolean;
  };
  const statusLock = useRef(false);
  const keyboardInput = useRef(false);
  const statusFocus = useRef<{
    origin: HTMLElement;
    taskId: string;
    undo: boolean;
  } | null>(null);
  useEffect(() => {
    const moved = (event: FocusEvent) => {
      if (
        statusFocus.current &&
        event.target !== statusFocus.current.origin &&
        event.target !== document.body
      ) {
        statusFocus.current = null;
      }
    };
    document.addEventListener("focusin", moved);
    return () => document.removeEventListener("focusin", moved);
  }, []);
  const [undo, setUndo] = useState<StatusAttempt | null>(null);
  const changeStatus = useMutation({
    mutationFn: ({ task, status, idempotencyKey }: StatusAttempt) =>
      client.updateTask(task.id, {
        title: task.title,
        description: task.description ?? "",
        epicId: task.epicId ?? null,
        assigneeUserId: task.assigneeUserId ?? null,
        dueAt: task.dueAt ?? null,
        deferredUntil: task.deferredUntil ?? null,
        expectedRevision: task.revision,
        status,
        idempotencyKey,
      }),
    onSuccess: async (saved, attempt) => {
      setUndo(
        attempt.undo
          ? null
          : {
              task: saved,
              status: attempt.task.status,
              idempotencyKey: crypto.randomUUID(),
              undo: true,
            },
      );
      await cache.invalidateQueries({ queryKey: ["tasks"] });
    },
    onSettled: () => {
      statusLock.current = false;
    },
  });
  useEffect(() => {
    const pending = statusFocus.current;
    if (changeStatus.isPending || !pending) return;
    statusFocus.current = null;
    // Only finish the keyboard journey when the user has not moved elsewhere
    // while the real mutation/refetch was pending.
    if (
      document.activeElement !== document.body &&
      document.activeElement !== pending.origin
    )
      return;
    const destination = changeStatus.isError
      ? document.getElementById("task-status-reload")
      : pending.undo
        ? document.getElementById(`task-complete-${pending.taskId}`)
        : document.getElementById("task-status-undo");
    (destination ?? document.getElementById("tasks-heading"))?.focus();
  }, [changeStatus.isPending, changeStatus.isError]);
  const submitStatus = (attempt: StatusAttempt, trigger?: HTMLElement) => {
    // React state is asynchronous: the ref also guards clicks in the same tick.
    if (statusLock.current) return;
    statusLock.current = true;
    statusFocus.current =
      keyboardInput.current && trigger
        ? { origin: trigger, taskId: attempt.task.id, undo: attempt.undo }
        : null;
    changeStatus.mutate(attempt);
  };
  const reloadStatus = async () => {
    await Promise.all([
      tasks.refetch(),
      lists.refetch(),
      ...(listId ? [selected.refetch()] : []),
    ]);
    setUndo(null);
    changeStatus.reset();
  };
  const statusConflict =
    changeStatus.error instanceof ApiError && changeStatus.error.status === 409;
  const statusDenied =
    changeStatus.error instanceof ApiError &&
    [401, 403, 404].includes(changeStatus.error.status);
  const error =
    create.error ?? selected.error ?? lists.error ?? tasks.error ?? epics.error;
  const detailTask = editing !== "new" ? (editing ?? target.data) : undefined;
  const detailCanEdit = editing ? editingCanEdit : targetList.data?.canEdit;
  return (
    <section
      className="tasks-workspace"
      aria-labelledby="tasks-heading"
      onKeyDownCapture={() => {
        keyboardInput.current = true;
      }}
      onPointerDownCapture={() => {
        keyboardInput.current = false;
      }}
    >
      <header className="tasks-toolbar">
        <div className="tasks-heading-block">
          <h1 id="tasks-heading" tabIndex={-1}>
            {listId ? (selected.data?.title ?? "Aufgabenliste") : "Aufgaben"}
          </h1>
          <span>
            {personalView
              ? "Meine persönliche Planung"
              : forMe
                ? "Für mich"
                : "Alle zugänglichen Aufgaben"}
          </span>
        </div>
        <div className="tasks-toolbar-actions" aria-label="Listenwerkzeuge">
          <TaskTool
            label="Liste wechseln"
            expanded={navigationOpen}
            controls="task-list-navigation"
            icon={FolderOpenIcon}
            onClick={() => {
              setNavigationOpen((open) => !open);
              setAccessOpen(false);
            }}
          />
          {selected.data?.canEdit && (
            <TaskTool
              label="Zugriff verwalten"
              expanded={accessOpen}
              controls="task-list-access"
              icon={UserGroupIcon}
              onClick={() => {
                setAccessOpen((open) => !open);
                setNavigationOpen(false);
              }}
            />
          )}
        </div>
      </header>
      {error && (
        <StatusMessage tone="error">
          <p>
            {error instanceof ApiError && error.status === 401
              ? "Bitte melde dich erneut an."
              : error instanceof ApiError && error.status === 404
                ? "Diese Liste ist nicht verfügbar oder du hast keinen Zugriff mehr."
                : "Die Aufgaben konnten nicht geladen oder gespeichert werden. Prüfe deine Verbindung und versuche es erneut."}
          </p>
          <Button
            variant="secondary"
            onClick={() => {
              void tasks.refetch();
              void lists.refetch();
              if (listId) void selected.refetch();
            }}
          >
            Erneut laden
          </Button>
        </StatusMessage>
      )}
      {navigationOpen && (
        <section
          id="task-list-navigation"
          className="tasks-tool-panel tasks-navigation"
          aria-labelledby="task-list-navigation-heading"
        >
          <div className="tasks-tool-panel-heading">
            <h2 id="task-list-navigation-heading">Aufgabenliste wechseln</h2>
            <Button
              variant="secondary"
              onClick={() => setNavigationOpen(false)}
            >
              Schließen
            </Button>
          </div>
          <ActionContextSearch contexts={contexts} />
          {(knownActions.length > 0 || listActionFilter) && (
            <label>
              Listen nach Aktion filtern
              <select
                value={listActionFilter}
                onChange={(event) => {
                  setListActionFilter(event.target.value);
                  setListOffset(0);
                }}
              >
                <option value="">Alle zugänglichen Listen</option>
                {listActionFilter &&
                  !knownActions.some(([id]) => id === listActionFilter) && (
                    <option value={listActionFilter}>
                      Ausgewählte Aktion beibehalten
                    </option>
                  )}
                {knownActions.map(([id, name]) => (
                  <option key={id} value={id}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <a href={basePath}>Alle zugänglichen Aufgaben</a>
          {lists.isPending ? (
            <p role="status">Listen werden geladen …</p>
          ) : (
            <ul className="tasks-list-links">
              {lists.data?.items.map((list) => (
                <li key={list.id}>
                  <a
                    href={`${basePath}/${list.id}`}
                    aria-current={list.id === listId ? "page" : undefined}
                  >
                    {list.title}
                  </a>
                </li>
              ))}
            </ul>
          )}
          {lists.data?.items.length === 0 && (
            <p>Noch keine Listen vorhanden.</p>
          )}
          <div className="tasks-paging">
            <Button
              variant="secondary"
              disabled={listOffset === 0}
              onClick={() => setListOffset(Math.max(0, listOffset - 50))}
            >
              Vorherige Listen
            </Button>
            <Button
              variant="secondary"
              disabled={lists.data?.nextOffset == null}
              onClick={() => setListOffset(lists.data!.nextOffset!)}
            >
              Weitere Listen
            </Button>
          </div>
          <details className="tasks-management">
            <summary>Neue Liste</summary>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                create.mutate();
              }}
            >
              <label>
                Kontext der neuen Liste
                <select
                  value={newListActionId}
                  disabled={create.isPending}
                  onChange={(event) => {
                    setNewListActionId(event.target.value);
                    operation.current = crypto.randomUUID();
                    create.reset();
                  }}
                >
                  <option value="">Eigenständig</option>
                  {newListActionId &&
                    !managedActions.some(([id]) => id === newListActionId) && (
                      <option value={newListActionId}>
                        Ausgewählte Aktion beibehalten
                      </option>
                    )}
                  {managedActions.map(([id, name]) => (
                    <option key={id} value={id}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
              <p>
                {newListActionId
                  ? "Aktuelle Mitglieder dieser Aktion können die Liste lesen. Die Aktionsverwaltung kann sie bearbeiten und zusätzliche Bearbeitungsrechte vergeben."
                  : "Die Liste ist zunächst nur für dich sichtbar."}
              </p>
              <label htmlFor="task-list-title">Name der Liste</label>
              <input
                id="task-list-title"
                required
                maxLength={240}
                value={title}
                disabled={create.isPending}
                onChange={(event) => {
                  setTitle(event.target.value);
                  operation.current = crypto.randomUUID();
                  create.reset();
                }}
              />
              <Button
                disabled={create.isPending || !title.trim()}
                type="submit"
              >
                {create.isPending ? "Wird angelegt …" : "Liste anlegen"}
              </Button>
            </form>
          </details>
        </section>
      )}
      {accessOpen && selected.data?.canEdit && (
        <section
          id="task-list-access"
          className="tasks-tool-panel tasks-access"
          aria-labelledby="task-list-access-heading"
        >
          <div className="tasks-tool-panel-heading">
            <h2 id="task-list-access-heading">Zugriff verwalten</h2>
            <Button variant="secondary" onClick={() => setAccessOpen(false)}>
              Schließen
            </Button>
          </div>
          <ListMembersPanel
            client={client}
            listId={selected.data.id}
            actionScoped={!!selected.data.actionId}
          />
        </section>
      )}
      <div
        className={`tasks-layout${detailTaskId ? " tasks-layout--detail" : ""}`}
      >
        <main className="tasks-main">
          {(!listId || selected.data?.canEdit) && (
            <QuickTaskForm
              client={client}
              identity={identity}
              list={selected.data}
              lists={lists.data?.items ?? []}
              scope={forMe ? "mine" : "all"}
              onCreated={() => tasks.refetch()}
            />
          )}
          {changeStatus.error ? (
            <StatusMessage tone="error">
              <p>
                {statusConflict
                  ? "Die Aufgabe wurde inzwischen geändert. Lade die Aufgaben neu; deine Änderung wurde nicht übernommen."
                  : statusDenied
                    ? "Du darfst diese Aufgabe nicht mehr bearbeiten. Lade die Aufgaben neu."
                    : "Der Speicherstatus ist unklar. Versuche denselben Vorgang erneut oder lade die Aufgaben neu."}
              </p>
              {!statusConflict && !statusDenied && (
                <Button
                  variant="secondary"
                  disabled={changeStatus.isPending}
                  onClick={(event) =>
                    changeStatus.variables &&
                    submitStatus(changeStatus.variables, event.currentTarget)
                  }
                >
                  Erneut versuchen
                </Button>
              )}
              <Button
                id="task-status-reload"
                variant="secondary"
                onClick={() => void reloadStatus()}
              >
                Neu laden
              </Button>
            </StatusMessage>
          ) : undo ? (
            <div className="tasks-undo" role="status">
              <span>
                {undo.task.status === "done"
                  ? "Aufgabe erledigt."
                  : "Aufgabe wieder geöffnet."}
              </span>
              <Button
                variant="secondary"
                disabled={changeStatus.isPending}
                id="task-status-undo"
                onClick={(event) => submitStatus(undo, event.currentTarget)}
              >
                Rückgängig
              </Button>
            </div>
          ) : changeStatus.isPending ? (
            <p role="status">Status wird gespeichert …</p>
          ) : null}
          {reorder.error && (
            <StatusMessage tone="error">
              <p>
                {reorder.error instanceof ApiError &&
                reorder.error.status === 409
                  ? "Die Reihenfolge wurde inzwischen geändert. Lade sie neu; die Bewegung wurde nicht übernommen."
                  : reorder.error instanceof ApiError &&
                      [401, 403, 404].includes(reorder.error.status)
                    ? "Du darfst diese Reihenfolge nicht mehr ändern. Lade die Aufgaben neu."
                    : "Der Speicherstatus der Bewegung ist unklar. Wiederhole denselben Vorgang oder lade die Reihenfolge neu."}
              </p>
              {!(
                reorder.error instanceof ApiError &&
                [401, 403, 404, 409].includes(reorder.error.status)
              ) &&
                reorder.variables && (
                  <Button
                    variant="secondary"
                    disabled={reorder.isPending}
                    onClick={() => reorder.mutate(reorder.variables!)}
                  >
                    Erneut versuchen
                  </Button>
                )}
              <Button
                id="task-order-reload"
                variant="secondary"
                disabled={reorder.isPending}
                onClick={() => void reloadOrder()}
              >
                Neu laden
              </Button>
            </StatusMessage>
          )}
          <p className="sr-only" role="status" aria-live="polite">
            {moveMessage}
          </p>
          <div className="tasks-filters">
            <label className="tasks-filter-scope">
              Bereich
              <select
                value={forMe ? "mine" : "all"}
                disabled={!!personalView}
                onChange={(event) => {
                  const scope = event.target.value as TaskScope;
                  setForMe(scope === "mine");
                  updateUrl({ scope });
                }}
              >
                <option value="mine">Für mich</option>
                <option value="all">Alle Aufgaben</option>
              </select>
            </label>
            <label className="tasks-filter-status">
              Ansicht
              <select
                value={status}
                onChange={(event) => {
                  const view = event.target.value as TaskView;
                  setStatus(view);
                  if (planView(view)) {
                    setForMe(true);
                    setSearch("");
                    setSort("manual");
                    updateUrl({
                      view,
                      scope: "mine",
                      search: "",
                      sort: "manual",
                    });
                  } else if (!listId && sort === "manual") {
                    setSort("created");
                    updateUrl({ view, sort: "created" });
                  } else {
                    updateUrl({ view });
                  }
                }}
              >
                <option value="open">Offen</option>
                <option value="due-today">Heute fällig</option>
                <option value="due-next">Demnächst fällig</option>
                <option value="deferred">Zurückgestellt</option>
                <option value="done">Erledigt</option>
                {!listId && <option value="plan-today">Mein Heute</option>}
                {!listId && <option value="plan-planned">Meine Planung</option>}
                {!listId && <option value="plan-someday">Irgendwann</option>}
              </select>
            </label>
            <label className="tasks-filter-search">
              Aufgaben suchen
              <input
                type="search"
                maxLength={200}
                disabled={!!personalView}
                value={search}
                onChange={(event) => {
                  const nextSearch = event.target.value;
                  setSearch(nextSearch);
                  updateUrl({ search: nextSearch });
                }}
              />
            </label>
            <label className="tasks-filter-sort">
              Sortierung
              <select
                value={sort}
                disabled={!!personalView}
                onChange={(event) => {
                  const nextSort = event.target.value as TaskSort;
                  setSort(nextSort);
                  setCollapsedSections(new Set());
                  updateUrl({ sort: nextSort });
                }}
              >
                <option value="created">Erstellreihenfolge</option>
                <option value="due">Fälligkeit</option>
                {listId && <option value="section">Abschnitte</option>}
                {(listId || personalView) && (
                  <option value="manual">Manuell</option>
                )}
              </select>
            </label>
          </div>
          {tasks.isPending ? (
            <p role="status">Aufgaben werden geladen …</p>
          ) : taskItems.length === 0 ? (
            <p role="status">
              {search
                ? "Keine Aufgaben für diese Suche."
                : status === "plan-today"
                  ? "Heute ist nichts persönlich eingeplant oder fällig."
                  : status === "plan-planned"
                    ? "Keine zukünftige persönliche Planung."
                    : status === "plan-someday"
                      ? "Keine Aufgaben für Irgendwann."
                      : status === "done"
                        ? "Noch keine erledigten Aufgaben für diese Auswahl."
                        : status === "due-today"
                          ? "Heute ist für diese Auswahl nichts fällig."
                          : status === "due-next"
                            ? "In den nächsten sieben Tagen ist für diese Auswahl nichts fällig."
                            : status === "deferred"
                              ? "Keine zurückgestellten Aufgaben für diese Auswahl."
                              : "Keine offenen Aufgaben für diese Auswahl."}
            </p>
          ) : (
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={finishDrag}
              onDragCancel={() => setMoveMessage("Verschieben abgebrochen.")}
              accessibility={{
                screenReaderInstructions: {
                  draggable:
                    "Zum Verschieben Leertaste drücken, mit den Pfeiltasten bewegen und mit Leertaste ablegen. Escape bricht ab.",
                },
                announcements: {
                  onDragStart: () => "Aufgabe aufgenommen.",
                  onDragOver: ({ over }) =>
                    over ? "Neue Position gewählt." : "Kein Ziel gewählt.",
                  onDragEnd: ({ over }) =>
                    over ? "Aufgabe abgelegt." : "Verschieben abgebrochen.",
                  onDragCancel: () => "Verschieben abgebrochen.",
                },
              }}
            >
              <SortableContext
                items={movableTaskIds}
                strategy={verticalListSortingStrategy}
              >
                <ul className="tasks-results">
                  {taskItems.map((task, index) => {
                    const planningTask = isPlannedTask(task) ? task : null;
                    const planned = planningTask?.personalPlan;
                    const planSource = planningTask?.planSource;
                    const previousTask = taskItems[index - 1];
                    const previousPlan =
                      previousTask && isPlannedTask(previousTask)
                        ? previousTask
                        : null;
                    const sectionId =
                      status === "plan-today"
                        ? (planSource ?? "planned")
                        : status === "plan-planned"
                          ? (planned?.plannedOn ?? "planned")
                          : (task.epicId ?? "unassigned");
                    const previousSectionId =
                      index === 0
                        ? null
                        : status === "plan-today"
                          ? (previousPlan?.planSource ?? "planned")
                          : status === "plan-planned"
                            ? (previousPlan?.personalPlan?.plannedOn ??
                              "planned")
                            : (taskItems[index - 1]?.epicId ?? "unassigned");
                    const startsSection =
                      (sort === "section" ||
                        sort === "manual" ||
                        status === "plan-today" ||
                        status === "plan-planned") &&
                      sectionId !== previousSectionId;
                    const collapsed = collapsedSections.has(sectionId);
                    const movable = canMove(task);
                    const movableIndex = movableTaskIds.indexOf(task.id);
                    const previousMovable = movableTasks[movableIndex - 1];
                    const nextMovable = movableTasks[movableIndex + 1];
                    return (
                      <Fragment key={task.id}>
                        {startsSection && (
                          <li
                            className="task-section-heading"
                            data-section-id={sectionId}
                          >
                            <button
                              type="button"
                              aria-expanded={!collapsed}
                              onClick={() =>
                                setCollapsedSections((current) => {
                                  const next = new Set(current);
                                  if (next.has(sectionId))
                                    next.delete(sectionId);
                                  else next.add(sectionId);
                                  return next;
                                })
                              }
                            >
                              <span
                                className="task-section-chevron"
                                aria-hidden="true"
                              />
                              <h2>
                                {status === "plan-today"
                                  ? planSource === "due"
                                    ? "Heute fällig / Überfällig"
                                    : "Persönlich geplant"
                                  : status === "plan-planned" &&
                                      planned?.plannedOn
                                    ? calendarDate(planned.plannedOn)
                                    : (task.epicTitle ?? "Ohne Abschnitt")}
                              </h2>
                            </button>
                          </li>
                        )}
                        {!collapsed && (
                          <SortableTaskRow
                            task={task}
                            movable={movable}
                            disabled={reorder.isPending || !!reorder.error}
                          >
                            {(handle) => (
                              <>
                                {task.canEdit ? (
                                  <input
                                    className="task-complete"
                                    id={`task-complete-${task.id}`}
                                    type="checkbox"
                                    aria-label={`${task.status === "done" ? "Aufgabe wieder öffnen" : "Aufgabe abschließen"}: ${task.title}`}
                                    checked={task.status === "done"}
                                    disabled={
                                      changeStatus.isPending ||
                                      !!changeStatus.error ||
                                      !!editing
                                    }
                                    onChange={(event) =>
                                      submitStatus(
                                        {
                                          task,
                                          status:
                                            task.status === "done"
                                              ? "open"
                                              : "done",
                                          idempotencyKey: crypto.randomUUID(),
                                          undo: false,
                                        },
                                        event.currentTarget,
                                      )
                                    }
                                  />
                                ) : (
                                  <span className="task-read-status">
                                    {task.status === "done"
                                      ? "Erledigt"
                                      : "Offen"}
                                  </span>
                                )}
                                <div className="task-row-body">
                                  <h2 aria-label={task.title}>
                                    <button
                                      className="task-title"
                                      id={`task-open-${task.id}`}
                                      aria-label={task.title}
                                      aria-describedby={`task-metadata-${task.id}`}
                                      disabled={
                                        !!editing || changeStatus.isPending
                                      }
                                      onClick={(event) => {
                                        closeTaskMenu(event.currentTarget);
                                        openTask(
                                          task,
                                          task.canEdit,
                                          event.currentTarget,
                                        );
                                      }}
                                    >
                                      <span className="task-title-text">
                                        {task.title}
                                      </span>
                                      <span
                                        className="task-metadata"
                                        id={`task-metadata-${task.id}`}
                                      >
                                        {!listId && (
                                          <span>{task.listTitle}</span>
                                        )}
                                        {!listId && task.actionTitle && (
                                          <span>{task.actionTitle}</span>
                                        )}
                                        <span>
                                          {task.assigneeName ??
                                            "Nicht zugewiesen"}
                                        </span>
                                        {task.epicTitle && (
                                          <span>{task.epicTitle}</span>
                                        )}
                                        {task.canEdit &&
                                          task.status === "done" && (
                                            <span>Erledigt</span>
                                          )}
                                        {task.dueAt && (
                                          <span>
                                            Fällig{" "}
                                            <time dateTime={task.dueAt}>
                                              {date(task.dueAt)}
                                            </time>
                                          </span>
                                        )}
                                        {task.deferredUntil && (
                                          <span>
                                            Zurückgestellt bis{" "}
                                            <time dateTime={task.deferredUntil}>
                                              {date(task.deferredUntil)}
                                            </time>
                                          </span>
                                        )}
                                        {planned?.plannedOn && (
                                          <span>
                                            Persönlich geplant für{" "}
                                            <time dateTime={planned.plannedOn}>
                                              {calendarDate(planned.plannedOn)}
                                            </time>
                                          </span>
                                        )}
                                        {planned?.state === "someday" && (
                                          <span>Persönlich: Irgendwann</span>
                                        )}
                                        {planSource === "due" && (
                                          <span>Fälligkeitshinweis</span>
                                        )}
                                      </span>
                                    </button>
                                  </h2>
                                </div>
                                {handle}
                                <details className="task-row-menu">
                                  <summary
                                    aria-label={`Aktionen für ${task.title}`}
                                  >
                                    <HugeiconsIcon
                                      icon={MoreHorizontalIcon}
                                      size={20}
                                      aria-hidden="true"
                                    />
                                  </summary>
                                  <div>
                                    <Button
                                      variant="secondary"
                                      disabled={
                                        !!editing || changeStatus.isPending
                                      }
                                      onClick={(event) =>
                                        openTask(
                                          task,
                                          task.canEdit,
                                          event.currentTarget,
                                        )
                                      }
                                    >
                                      {task.canEdit ? "Bearbeiten" : "Details"}
                                    </Button>
                                    {movable && (
                                      <>
                                        <div
                                          className="task-menu-directions"
                                          aria-label="Reihenfolge ändern"
                                        >
                                          <button
                                            type="button"
                                            className="task-menu-action"
                                            disabled={
                                              !previousMovable ||
                                              reorder.isPending
                                            }
                                            onClick={(event) => {
                                              closeTaskMenu(
                                                event.currentTarget,
                                              );
                                              if (previousMovable)
                                                submitMove(
                                                  task,
                                                  {
                                                    before: previousMovable.id,
                                                  },
                                                  { target: previousMovable },
                                                );
                                            }}
                                          >
                                            <HugeiconsIcon
                                              icon={ArrowUp01Icon}
                                              size={18}
                                              aria-hidden="true"
                                            />
                                            Nach oben
                                          </button>
                                          <button
                                            type="button"
                                            className="task-menu-action"
                                            disabled={
                                              !nextMovable || reorder.isPending
                                            }
                                            onClick={(event) => {
                                              closeTaskMenu(
                                                event.currentTarget,
                                              );
                                              if (nextMovable)
                                                submitMove(
                                                  task,
                                                  { after: nextMovable.id },
                                                  { target: nextMovable },
                                                );
                                            }}
                                          >
                                            <HugeiconsIcon
                                              icon={ArrowDown01Icon}
                                              size={18}
                                              aria-hidden="true"
                                            />
                                            Nach unten
                                          </button>
                                        </div>
                                        {!personalView && listId && (
                                          <form
                                            className="task-menu-move"
                                            onSubmit={(event) => {
                                              event.preventDefault();
                                              closeTaskMenu(
                                                event.currentTarget,
                                              );
                                              const value = String(
                                                new FormData(
                                                  event.currentTarget,
                                                ).get("epic") ?? "",
                                              );
                                              submitMove(
                                                task,
                                                { edge: "end" },
                                                { targetEpicId: value || null },
                                              );
                                            }}
                                          >
                                            <label>
                                              In Abschnitt
                                              <select
                                                name="epic"
                                                defaultValue={task.epicId ?? ""}
                                                disabled={epics.isPending}
                                              >
                                                <option value="">
                                                  Ohne Abschnitt
                                                </option>
                                                {epics.data?.items.map(
                                                  (epic) => (
                                                    <option
                                                      key={epic.id}
                                                      value={epic.id}
                                                    >
                                                      {epic.title}
                                                    </option>
                                                  ),
                                                )}
                                              </select>
                                            </label>
                                            <button
                                              type="submit"
                                              className="task-menu-action"
                                              disabled={
                                                reorder.isPending ||
                                                epics.isPending
                                              }
                                            >
                                              <HugeiconsIcon
                                                icon={FolderOpenIcon}
                                                size={18}
                                                aria-hidden="true"
                                              />
                                              Verschieben
                                            </button>
                                          </form>
                                        )}
                                        {personalView && planned && (
                                          <form
                                            className="task-menu-move"
                                            onSubmit={(event) => {
                                              event.preventDefault();
                                              closeTaskMenu(
                                                event.currentTarget,
                                              );
                                              const targetDate = String(
                                                new FormData(
                                                  event.currentTarget,
                                                ).get("plannedOn") ?? "",
                                              );
                                              if (targetDate)
                                                submitMove(
                                                  task,
                                                  { edge: "end" },
                                                  { targetDate },
                                                );
                                            }}
                                          >
                                            <label>
                                              Für Tag planen
                                              <input
                                                name="plannedOn"
                                                type="date"
                                                required
                                                defaultValue={
                                                  planned.plannedOn ??
                                                  localToday()
                                                }
                                              />
                                            </label>
                                            <button
                                              type="submit"
                                              className="task-menu-action"
                                              disabled={reorder.isPending}
                                            >
                                              <HugeiconsIcon
                                                icon={Calendar03Icon}
                                                size={18}
                                                aria-hidden="true"
                                              />
                                              Planen
                                            </button>
                                          </form>
                                        )}
                                      </>
                                    )}
                                  </div>
                                </details>
                              </>
                            )}
                          </SortableTaskRow>
                        )}
                      </Fragment>
                    );
                  })}
                </ul>
              </SortableContext>
            </DndContext>
          )}
          {tasks.hasNextPage && (
            <div className="tasks-paging">
              <Button
                variant="secondary"
                disabled={tasks.isFetchingNextPage}
                onClick={() => void tasks.fetchNextPage()}
              >
                {tasks.isFetchingNextPage
                  ? "Weitere Aufgaben werden geladen …"
                  : "Weitere Aufgaben"}
              </Button>
            </div>
          )}
        </main>
        {detailTaskId && (
          <aside className="tasks-detail-panel" aria-label="Aufgabendetails">
            {!detailTask ||
            target.isPending ||
            (!editing && targetList.isPending) ? (
              <p role="status">Aufgabe wird geladen …</p>
            ) : target.isError ||
              targetList.isError ||
              (listId && detailTask.listId !== listId) ? (
              <StatusMessage tone="error">
                <p>Aufgabe nicht verfügbar oder kein Zugriff.</p>
                <Button variant="secondary" onClick={() => closeEditor(true)}>
                  Zur Aufgabenliste
                </Button>
              </StatusMessage>
            ) : detailCanEdit ? (
              <>
                <TaskEditor
                  key={detailTask.id}
                  client={client}
                  userId={identity.userId}
                  listId={detailTask.listId}
                  task={detailTask}
                  onDirtyChange={(dirty) => {
                    editorDirty.current = dirty;
                  }}
                  onClose={() => closeEditor()}
                />
                <TaskPlanPanel client={client} taskId={detailTask.id} />
              </>
            ) : (
              <>
                <div className="task-editor">
                  <TaskReadOnly task={detailTask} focusOnOpen />
                  <Button variant="secondary" onClick={() => closeEditor(true)}>
                    Schließen
                  </Button>
                </div>
                <TaskPlanPanel client={client} taskId={detailTask.id} />
              </>
            )}
          </aside>
        )}
      </div>
    </section>
  );
}

function TaskReadOnly({
  task,
  focusOnOpen = false,
}: {
  task: Task;
  focusOnOpen?: boolean;
}) {
  const heading = useRef<HTMLHeadingElement | null>(null);
  useEffect(() => {
    if (focusOnOpen) heading.current?.focus();
  }, [focusOnOpen]);
  return (
    <article className="task-read-only">
      <h2 ref={heading} tabIndex={-1}>
        {task.title}
      </h2>
      <p>{task.description}</p>
      <p>{task.status === "done" ? "Erledigt" : "Offen"}</p>
      {task.dueAt && (
        <p>
          Fällig <time dateTime={task.dueAt}>{date(task.dueAt)}</time>
        </p>
      )}
      {task.deferredUntil && (
        <p>
          Zurückgestellt bis{" "}
          <time dateTime={task.deferredUntil}>{date(task.deferredUntil)}</time>
        </p>
      )}
    </article>
  );
}
