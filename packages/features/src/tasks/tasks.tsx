import { useMutation, useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { ApiError } from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";
import type { ModulePageContext } from "../modules";
import "./tasks.css";

function date(value: string) {
  return new Intl.DateTimeFormat("de-DE", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function TasksPage({
  client,
  basePath,
  listId,
}: ModulePageContext & { basePath: string; listId?: string }) {
  const [forMe, setForMe] = useState(!listId);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [listOffset, setListOffset] = useState(0);
  const [status, setStatus] = useState<"open" | "done">("open");
  const [includeDeferred, setIncludeDeferred] = useState(false);
  const [title, setTitle] = useState("");
  const operation = useRef(crypto.randomUUID());
  const lists = useQuery({
    queryKey: ["task-lists", listOffset],
    queryFn: () => client.listTaskLists({ offset: listOffset }),
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
        idempotencyKey: operation.current,
      }),
    onSuccess: (list) => window.location.assign(`${basePath}/${list.id}`),
  });
  const error = create.error ?? selected.error ?? lists.error ?? tasks.error;
  const reset = () => setOffset(0);
  return (
    <section className="tasks-workspace" aria-labelledby="tasks-heading">
      <header>
        <h1 id="tasks-heading">
          {listId ? (selected.data?.title ?? "Aufgabenliste") : "Aufgaben"}
        </h1>
        <p>
          Gemeinsam vorbereiten, Zuständigkeiten sehen und den nächsten Schritt
          finden.
        </p>
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
            <p>Die Liste ist zunächst nur für dich sichtbar.</p>
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
