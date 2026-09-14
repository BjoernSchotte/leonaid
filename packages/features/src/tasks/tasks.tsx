import {
  Add01Icon,
  FolderOpenIcon,
  MoreHorizontalIcon,
  UserGroupIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ApiError } from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";
import type { ModulePageContext } from "../modules";
import { ListMembersPanel } from "./list-members";
import { TaskEditor, type Task } from "./task-editor";
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

type TaskView = "open" | "done";
type TaskScope = "mine" | "all";

function taskLocation(defaultScope: TaskScope = "mine") {
  const query = new URLSearchParams(window.location.search);
  return {
    scope:
      query.get("scope") === "all"
        ? ("all" as const)
        : query.get("scope") === "mine"
          ? ("mine" as const)
          : defaultScope,
    view: query.get("view") === "done" ? ("done" as const) : ("open" as const),
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
  const initialLocation = useRef(taskLocation(listId ? "all" : "mine")).current;
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
  const [forMe, setForMe] = useState(initialLocation.scope === "mine");
  const [search, setSearch] = useState(initialLocation.search);
  const [offset, setOffset] = useState(0);
  const [listOffset, setListOffset] = useState(0);
  const [status, setStatus] = useState<TaskView>(initialLocation.view);
  const [includeDeferred, setIncludeDeferred] = useState(false);
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
  const updateUrl = (
    values: Partial<{
      scope: TaskScope;
      view: TaskView;
      search: string;
      taskId: string | null;
    }>,
    mode: "push" | "replace" = "replace",
  ) => {
    const url = new URL(window.location.href);
    const nextScope = values.scope ?? (forMe ? "mine" : "all");
    const nextView = values.view ?? status;
    const nextSearch = values.search ?? search;
    const nextTask = values.taskId === undefined ? detailTaskId : values.taskId;
    url.searchParams.set("scope", nextScope);
    url.searchParams.set("view", nextView);
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
      setForMe(location.scope === "mine");
      setStatus(location.view);
      setSearch(location.search);
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
  const tasks = useQuery({
    queryKey: ["tasks", listId, forMe, search, offset, status, includeDeferred],
    queryFn: () =>
      client.listTasks({
        listId,
        forMe,
        search,
        offset,
        status,
        includeDeferred,
      }),
    retry: false,
  });
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
  const error = create.error ?? selected.error ?? lists.error ?? tasks.error;
  const reset = () => setOffset(0);
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
          <span>{forMe ? "Für mich" : "Alle zugänglichen Aufgaben"}</span>
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
          <div className="tasks-filters">
            <label className="tasks-filter-scope">
              Ansicht
              <select
                value={forMe ? "mine" : "all"}
                onChange={(event) => {
                  const scope = event.target.value as TaskScope;
                  setForMe(scope === "mine");
                  updateUrl({ scope });
                  reset();
                }}
              >
                <option value="mine">Für mich</option>
                <option value="all">Alle zugänglichen Aufgaben</option>
              </select>
            </label>
            <label className="tasks-filter-status">
              Status
              <select
                value={status}
                onChange={(event) => {
                  const view = event.target.value as TaskView;
                  setStatus(view);
                  updateUrl({ view });
                  reset();
                }}
              >
                <option value="open">Offen</option>
                <option value="done">Erledigt</option>
              </select>
            </label>
            <label className="tasks-filter-search">
              Aufgaben suchen
              <input
                type="search"
                maxLength={200}
                value={search}
                onChange={(event) => {
                  const nextSearch = event.target.value;
                  setSearch(nextSearch);
                  updateUrl({ search: nextSearch });
                  reset();
                }}
              />
            </label>
            <label className="tasks-checkbox tasks-filter-deferred">
              <input
                type="checkbox"
                checked={includeDeferred}
                onChange={(event) => {
                  setIncludeDeferred(event.target.checked);
                  reset();
                }}
              />
              Zurückgestellte anzeigen
            </label>
          </div>
          {tasks.isPending ? (
            <p role="status">Aufgaben werden geladen …</p>
          ) : tasks.data?.items.length === 0 ? (
            <p role="status">
              {search
                ? "Keine Aufgaben für diese Suche."
                : status === "done"
                  ? "Noch keine erledigten Aufgaben für diese Auswahl."
                  : "Keine offenen Aufgaben für diese Auswahl."}
            </p>
          ) : (
            <ul className="tasks-results">
              {tasks.data?.items.map((task) => (
                <li key={task.id} className="task-row">
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
                            status: task.status === "done" ? "open" : "done",
                            idempotencyKey: crypto.randomUUID(),
                            undo: false,
                          },
                          event.currentTarget,
                        )
                      }
                    />
                  ) : (
                    <span className="task-read-status">
                      {task.status === "done" ? "Erledigt" : "Offen"}
                    </span>
                  )}
                  <div className="task-row-body">
                    <h2 aria-label={task.title}>
                      <button
                        className="task-title"
                        id={`task-open-${task.id}`}
                        aria-label={task.title}
                        aria-describedby={`task-metadata-${task.id}`}
                        disabled={!!editing || changeStatus.isPending}
                        onClick={(event) =>
                          openTask(task, task.canEdit, event.currentTarget)
                        }
                      >
                        <span className="task-title-text">{task.title}</span>
                        <span
                          className="task-metadata"
                          id={`task-metadata-${task.id}`}
                        >
                          {!listId && <span>{task.listTitle}</span>}
                          {!listId && task.actionTitle && (
                            <span>{task.actionTitle}</span>
                          )}
                          <span>{task.assigneeName ?? "Nicht zugewiesen"}</span>
                          {task.epicTitle && <span>{task.epicTitle}</span>}
                          {task.canEdit && task.status === "done" && (
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
                        </span>
                      </button>
                    </h2>
                  </div>
                  <details className="task-row-menu">
                    <summary aria-label={`Aktionen für ${task.title}`}>
                      <HugeiconsIcon
                        icon={MoreHorizontalIcon}
                        size={20}
                        aria-hidden="true"
                      />
                    </summary>
                    <div>
                      {" "}
                      <Button
                        variant="secondary"
                        disabled={!!editing || changeStatus.isPending}
                        onClick={(event) =>
                          openTask(task, task.canEdit, event.currentTarget)
                        }
                      >
                        {task.canEdit ? "Bearbeiten" : "Details"}
                      </Button>
                    </div>
                  </details>
                </li>
              ))}
            </ul>
          )}
          <div className="tasks-paging">
            <Button
              variant="secondary"
              disabled={offset === 0 || tasks.isFetching}
              onClick={() => setOffset(Math.max(0, offset - 50))}
            >
              Zurück
            </Button>
            <Button
              variant="secondary"
              disabled={tasks.data?.nextOffset == null || tasks.isFetching}
              onClick={() => setOffset(tasks.data!.nextOffset!)}
            >
              Weitere Aufgaben
            </Button>
          </div>
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
            ) : (
              <div className="task-editor">
                <TaskReadOnly task={detailTask} focusOnOpen />
                <Button variant="secondary" onClick={() => closeEditor(true)}>
                  Schließen
                </Button>
              </div>
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
