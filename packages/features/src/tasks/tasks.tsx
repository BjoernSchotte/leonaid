import { Add01Icon, MoreHorizontalIcon } from "@hugeicons/core-free-icons";
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

export function TasksPage({
  client,
  identity,
  basePath,
  listId,
}: ModulePageContext & { basePath: string; listId?: string }) {
  const cache = useQueryClient();
  const [navigationOpen, setNavigationOpen] = useState(
    () => window.matchMedia("(min-width: 1100px)").matches,
  );
  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 1100px)");
    const update = () => setNavigationOpen(desktop.matches);
    desktop.addEventListener("change", update);
    return () => desktop.removeEventListener("change", update);
  }, []);
  const targetId = new URLSearchParams(window.location.search).get("task");
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
  const editorTrigger = useRef<HTMLButtonElement | null>(null);
  const closeEditor = () => {
    setEditing(null);
    requestAnimationFrame(() => {
      if (editorTrigger.current?.isConnected) editorTrigger.current.focus();
      else document.getElementById("tasks-heading")?.focus();
    });
  };
  const [forMe, setForMe] = useState(!listId);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [listOffset, setListOffset] = useState(0);
  const [status, setStatus] = useState<"open" | "done">("open");
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
  if (targetId) {
    return (
      <section className="tasks-workspace">
        <h1>Aufgabe</h1>
        <a href={listId ? `${basePath}/${listId}` : basePath}>
          Zur Aufgabenliste
        </a>
        {target.isPending || (target.data && targetList.isPending) ? (
          <p role="status">Aufgabe wird geladen …</p>
        ) : target.isError ||
          !target.data ||
          targetList.isError ||
          !targetList.data ||
          (listId && target.data.listId !== listId) ? (
          <StatusMessage tone="error">
            Aufgabe nicht verfügbar oder kein Zugriff.
          </StatusMessage>
        ) : !targetList.data.canEdit ? (
          <TaskReadOnly task={target.data} />
        ) : (
          <TaskEditor
            client={client}
            userId={identity.userId}
            listId={target.data.listId}
            task={target.data}
            onClose={() =>
              window.location.assign(`${basePath}/${target.data.listId}`)
            }
          />
        )}
      </section>
    );
  }
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
      <header>
        <h1 id="tasks-heading" tabIndex={-1}>
          {listId ? (selected.data?.title ?? "Aufgabenliste") : "Aufgaben"}
        </h1>
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
      <div className="tasks-columns">
        <aside aria-label="Aufgabenlisten">
          <details
            className="tasks-management tasks-navigation"
            open={navigationOpen}
            onToggle={(event) => setNavigationOpen(event.currentTarget.open)}
          >
            <summary>Listen wechseln</summary>
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
                      !managedActions.some(
                        ([id]) => id === newListActionId,
                      ) && (
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
          </details>
        </aside>
        <div>
          {selected.data?.canEdit && (
            <details className="tasks-management tasks-access">
              <summary>Zugriff verwalten</summary>
              <ListMembersPanel
                client={client}
                listId={selected.data.id}
                actionScoped={!!selected.data.actionId}
              />
            </details>
          )}
          {listId && selected.data?.canEdit && !editing && (
            <Button
              icon={
                <HugeiconsIcon icon={Add01Icon} size={20} aria-hidden="true" />
              }
              onClick={(event) => {
                editorTrigger.current = event.currentTarget;
                setEditingCanEdit(true);
                setEditing("new");
              }}
            >
              Neue Aufgabe
            </Button>
          )}
          {editing && editing !== "new" && !editingCanEdit && (
            <div className="task-editor">
              <TaskReadOnly task={editing} focusOnOpen />
              <Button variant="secondary" onClick={closeEditor}>
                Schließen
              </Button>
            </div>
          )}
          {editing && editingCanEdit && (
            <TaskEditor
              key={editing === "new" ? "new" : editing.id}
              client={client}
              userId={identity.userId}
              listId={editing === "new" ? listId! : editing.listId}
              task={editing === "new" ? undefined : editing}
              onClose={closeEditor}
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
            <label>
              Ansicht
              <select
                value={forMe ? "mine" : "all"}
                onChange={(event) => {
                  setForMe(event.target.value === "mine");
                  reset();
                }}
              >
                <option value="mine">Für mich</option>
                <option value="all">Alle zugänglichen Aufgaben</option>
              </select>
            </label>
            <label>
              Status
              <select
                value={status}
                onChange={(event) => {
                  setStatus(event.target.value as "open" | "done");
                  reset();
                }}
              >
                <option value="open">Offen</option>
                <option value="done">Erledigt</option>
              </select>
            </label>
            <label>
              Aufgaben suchen
              <input
                type="search"
                maxLength={200}
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                  reset();
                }}
              />
            </label>
            <label className="tasks-checkbox">
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
                        aria-label={task.title}
                        aria-describedby={`task-metadata-${task.id}`}
                        disabled={!!editing || changeStatus.isPending}
                        onClick={(event) => {
                          editorTrigger.current = event.currentTarget;
                          setEditingCanEdit(task.canEdit);
                          setEditing(task);
                        }}
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
                        onClick={(event) => {
                          editorTrigger.current = event.currentTarget;
                          setEditingCanEdit(task.canEdit);
                          setEditing(task);
                        }}
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
        </div>
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
