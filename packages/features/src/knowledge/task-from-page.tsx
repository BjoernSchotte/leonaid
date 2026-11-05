import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { LeonAidApiClient } from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";
import { says, type Address } from "../tasks/task-copy";
import { TaskEditor, type Task } from "../tasks/task-editor";
import "../tasks/tasks.css";

export function TaskFromPage({
  address,
  client,
  userId,
  createTask,
  onClose,
}: {
  /** "Sie" in the back office, "du" in the app. */
  address: Address;
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
      className="task-from-page"
      aria-label="Aufgabe aus Seite erstellen"
    >
      {!listId ? (
        <>
          <h2>Aufgabenliste wählen</h2>
          <label className="field">
            <span className="field-label">Aufgabenlisten suchen</span>
            <input
              className="input"
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
          {lists.isPending && (
            <p className="field-hint" role="status">
              Listen werden geladen …
            </p>
          )}
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
              <p>
                {says(
                  address,
                  "Wähle eine Liste, in der du Aufgaben anlegen darfst.",
                  "Wählen Sie eine Liste, in der Sie Aufgaben anlegen dürfen.",
                )}
              </p>
              <ul className="task-list-links">
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
                  {says(
                    address,
                    "Keine passenden Listen. Lege bei Bedarf zuerst eine Liste im Bereich Aufgaben an.",
                    "Keine passenden Listen. Legen Sie bei Bedarf zuerst eine Liste im Bereich Aufgaben an.",
                  )}
                </p>
              )}
              <div className="task-form-actions">
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
          address={address}
          // The page has no reload control for this case: the browser
          // reload brings the current version.
          conflictMessage={says(
            address,
            "Die Seite wurde inzwischen geändert oder dieser Speicherversuch hat einen Konflikt. Dein Aufgabenentwurf bleibt hier erhalten. Kopiere deine Eingaben, lade die Seite neu und lege die Aufgabe erneut an.",
            "Die Seite wurde inzwischen geändert oder dieser Speicherversuch hat einen Konflikt. Ihr Aufgabenentwurf bleibt hier erhalten. Kopieren Sie Ihre Eingaben, laden Sie die Seite neu und legen Sie die Aufgabe erneut an.",
          )}
          createTask={(command) => createTask(listId, command)}
        />
      )}
    </section>
  );
}
