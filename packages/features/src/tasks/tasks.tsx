import { useMutation, useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { ApiError } from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";
import type { ModulePageContext } from "../modules";
import { ListMembersPanel } from "./list-members";
import { TaskEditor, type Task } from "./task-editor";
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
  const [editing, setEditing] = useState<Task | "new" | null>(null);
  const editorTrigger = useRef<HTMLButtonElement | null>(null);
  const [forMe, setForMe] = useState(!listId);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [listOffset, setListOffset] = useState(0);
  const [status, setStatus] = useState<"open" | "done">("open");
  const [includeDeferred, setIncludeDeferred] = useState(false);
  const [title, setTitle] = useState("");
  const [newListActionId, setNewListActionId] = useState("");
  const [listActionFilter, setListActionFilter] = useState("");
  const [actionSearch, setActionSearch] = useState("");
  const [actionOffset, setActionOffset] = useState(0);
  const contexts = useQuery({
    queryKey: ["task-action-contexts", actionSearch, actionOffset],
    queryFn: () =>
      client.listTaskActionContexts({
        search: actionSearch,
        offset: actionOffset,
      }),
    retry: false,
  });
  const knownActions = (contexts.data?.items ?? []).map(
    (action) => [action.actionId, action.name] as const,
  );
  const managedActions = (contexts.data?.items ?? [])
    .filter((action) => action.canCreateLists)
    .map((action) => [action.actionId, action.name] as const);
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
  const error = create.error ?? selected.error ?? lists.error ?? tasks.error;
  const reset = () => setOffset(0);
  return (
    <section className="tasks-workspace" aria-labelledby="tasks-heading">
      <header>
        <h1 id="tasks-heading" tabIndex={-1}>
          {listId ? (selected.data?.title ?? "Aufgabenliste") : "Aufgaben"}
        </h1>
        <p>
          Gemeinsam vorbereiten, Zuständigkeiten sehen und den nächsten Schritt
          finden.
        </p>
        {selected.data && (
          <p>
            {selected.data.actionId
              ? `Charity-Aktion: ${knownActions.find(([id]) => id === selected.data?.actionId)?.[1] ?? "Aktionsgebundene Liste"}`
              : "Eigenständige Liste mit ausdrücklich vergebenem Zugriff"}
          </p>
        )}
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
          <h2>Listen</h2>
          <details>
            <summary>Aktionen suchen</summary>
            <label>
              Aktionsname
              <input
                type="search"
                maxLength={200}
                value={actionSearch}
                onChange={(event) => {
                  setActionSearch(event.target.value);
                  setActionOffset(0);
                }}
              />
            </label>
            {contexts.isPending && (
              <p role="status">Aktionen werden geladen …</p>
            )}
            {contexts.error && (
              <StatusMessage tone="error">
                Aktionen konnten nicht geladen werden.{" "}
                <Button
                  variant="secondary"
                  onClick={() => void contexts.refetch()}
                >
                  Aktionen neu laden
                </Button>
              </StatusMessage>
            )}
            {contexts.data?.items.length === 0 && (
              <p>Keine zugänglichen Aktionen für diese Suche.</p>
            )}
            <div className="tasks-paging">
              <Button
                variant="secondary"
                disabled={actionOffset === 0 || contexts.isFetching}
                onClick={() => setActionOffset(Math.max(0, actionOffset - 50))}
              >
                Vorherige Aktionen
              </Button>
              <Button
                variant="secondary"
                disabled={
                  contexts.data?.nextOffset == null || contexts.isFetching
                }
                onClick={() => setActionOffset(contexts.data!.nextOffset!)}
              >
                Weitere Aktionen
              </Button>
            </div>
          </details>
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
          <form
            onSubmit={(event) => {
              event.preventDefault();
              create.mutate();
            }}
          >
            <h2>Neue Liste</h2>
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
            <Button disabled={create.isPending || !title.trim()} type="submit">
              {create.isPending ? "Wird angelegt …" : "Liste anlegen"}
            </Button>
          </form>
        </aside>
        <div>
          {selected.data && (
            <ListMembersPanel
              client={client}
              listId={selected.data.id}
              actionScoped={!!selected.data.actionId}
            />
          )}
          {listId && !editing && (
            <Button
              onClick={(event) => {
                editorTrigger.current = event.currentTarget;
                setEditing("new");
              }}
            >
              Neue Aufgabe
            </Button>
          )}
          {editing && (
            <TaskEditor
              key={editing === "new" ? "new" : editing.id}
              client={client}
              userId={identity.userId}
              listId={editing === "new" ? listId! : editing.listId}
              task={editing === "new" ? undefined : editing}
              onClose={() => {
                setEditing(null);
                requestAnimationFrame(() => {
                  if (editorTrigger.current?.isConnected)
                    editorTrigger.current.focus();
                  else document.getElementById("tasks-heading")?.focus();
                });
              }}
            />
          )}
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
              Keine Aufgaben für diese Auswahl. Ändere die Ansicht oder den
              Status, um weitere Aufgaben zu sehen.
            </p>
          ) : (
            <ul className="tasks-results">
              {tasks.data?.items.map((task) => (
                <li key={task.id}>
                  <h2>{task.title}</h2>
                  {task.description && <p>{task.description}</p>}
                  <dl>
                    <div>
                      <dt>Status</dt>
                      <dd>{task.status === "done" ? "Erledigt" : "Offen"}</dd>
                    </div>
                    {task.dueAt && (
                      <div>
                        <dt>Fällig</dt>
                        <dd>
                          <time dateTime={task.dueAt}>{date(task.dueAt)}</time>
                        </dd>
                      </div>
                    )}
                    {task.deferredUntil && (
                      <div>
                        <dt>Zurückgestellt bis</dt>
                        <dd>
                          <time dateTime={task.deferredUntil}>
                            {date(task.deferredUntil)}
                          </time>
                        </dd>
                      </div>
                    )}
                  </dl>
                  <Button
                    variant="secondary"
                    disabled={!!editing}
                    onClick={(event) => {
                      editorTrigger.current = event.currentTarget;
                      setEditing(task);
                    }}
                  >
                    Bearbeiten
                  </Button>
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
