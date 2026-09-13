import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { LeonAidApiClient } from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";
import { TaskEditor, type Task } from "../tasks/task-editor";
import "../tasks/tasks.css";

export function TaskFromPage({
  client,
  userId,
  createTask,
  onClose,
}: {
  client: LeonAidApiClient;
  userId: string;
  createTask: (
    listId: string,
    command: Parameters<LeonAidApiClient["createTask"]>[1],
  ) => Promise<Task>;
  onClose: () => void;
}) {
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [listId, setListId] = useState("");
  const lists = useQuery({
    queryKey: ["task-lists", "page-picker", search, offset],
    queryFn: () => client.listTaskLists({ search, offset }),
    retry: false,
  });
  return (
    <section
      className="tasks-workspace"
      aria-label="Aufgabe aus Seite erstellen"
    >
      {!listId ? (
        <>
          <h2>Aufgabenliste wählen</h2>
          <label>
            Aufgabenlisten suchen
            <input
              autoFocus
              type="search"
              value={search}
              maxLength={200}
              onChange={(event) => {
                setSearch(event.target.value);
                setOffset(0);
              }}
            />
          </label>
          {lists.isPending && <p role="status">Listen werden geladen …</p>}
          {lists.error && (
            <StatusMessage tone="error">
              <p>Die Listen konnten nicht geladen werden.</p>
              <Button variant="secondary" onClick={() => void lists.refetch()}>
                Erneut laden
              </Button>
            </StatusMessage>
          )}
          {lists.data && !lists.error && (
            <>
              <p>Wähle eine Liste, in der du Aufgaben anlegen darfst.</p>
              <ul className="tasks-list-links">
                {lists.data.items.map((list) => (
                  <li key={list.id}>
                    <Button
                      variant="secondary"
                      onClick={() => setListId(list.id)}
                    >
                      {list.title}
                    </Button>
                  </li>
                ))}
              </ul>
              {!lists.data.items.length && (
                <p>
                  Keine passenden Listen. Lege bei Bedarf zuerst eine Liste im
                  Bereich Aufgaben an.
                </p>
              )}
              <div className="tasks-paging">
                <Button
                  variant="secondary"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - 50))}
                >
                  Vorherige Listen
                </Button>
                <Button
                  variant="secondary"
                  disabled={lists.data.nextOffset === null}
                  onClick={() => setOffset(lists.data!.nextOffset!)}
                >
                  Weitere Listen
                </Button>
              </div>
            </>
          )}
          <Button variant="secondary" onClick={onClose}>
            Abbrechen
          </Button>
        </>
      ) : (
        <TaskEditor
          client={client}
          userId={userId}
          listId={listId}
          onClose={onClose}
          conflictMessage="Die Seite wurde inzwischen geändert oder dieser Speicherversuch hat einen Konflikt. Dein Aufgabenentwurf bleibt hier erhalten. Kopiere deine Eingaben, bevor du abbrichst. Wähle danach auf der Seite Aktuelle Version laden und lege die Aufgabe erneut an."
          createTask={(command) => createTask(listId, command)}
        />
      )}
    </section>
  );
}
