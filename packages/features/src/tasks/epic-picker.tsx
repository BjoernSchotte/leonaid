import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { ApiError, type LeonAidApiClient } from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

export function EpicPicker({
  client,
  listId,
  value,
  onChange,
}: {
  client: LeonAidApiClient;
  listId: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const cache = useQueryClient();
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [title, setTitle] = useState("");
  const operation = useRef(crypto.randomUUID());
  const epics = useQuery({
    queryKey: ["task-epics", listId, search, offset],
    queryFn: () => client.listTaskEpics(listId, { search, offset }),
    retry: false,
  });
  const selected = epics.data?.items.find((epic) => epic.id === value);
  const save = useMutation({
    mutationKey: ["task-epic-write", listId],
    mutationFn: (rename: boolean) => {
      const body = { title: title.trim(), idempotencyKey: operation.current };
      if (rename) {
        if (!selected) throw new Error("Epic selection unavailable");
        return client.updateTaskEpic(selected.id, {
          ...body,
          expectedRevision: selected.revision,
        });
      }
      return client.createTaskEpic(listId, body);
    },
    onSuccess: async (epic) => {
      onChange(epic.id);
      setTitle("");
      operation.current = crypto.randomUUID();
      setSearch("");
      setOffset(0);
      await cache.invalidateQueries({ queryKey: ["task-epics", listId] });
    },
  });
  return (
    <fieldset className="task-epic-picker" disabled={save.isPending}>
      <legend>Epic (optional)</legend>
      <label>
        Epics suchen
        <input
          type="search"
          value={search}
          maxLength={200}
          onChange={(event) => {
            setSearch(event.target.value);
            setOffset(0);
          }}
        />
      </label>
      <label>
        Epic auswählen
        <select
          value={value}
          onChange={(event) => {
            onChange(event.target.value);
            operation.current = crypto.randomUUID();
            save.reset();
          }}
        >
          <option value="">Kein Epic</option>
          {value && !selected && (
            <option value={value}>Aktuelle Zuordnung beibehalten</option>
          )}
          {epics.data?.items.map((epic) => (
            <option key={epic.id} value={epic.id}>
              {epic.title}
            </option>
          ))}
        </select>
      </label>
      {epics.isPending && <p role="status">Epics werden geladen …</p>}
      {epics.error && (
        <StatusMessage tone="error">
          Epics konnten nicht geladen werden. Die aktuelle Zuordnung bleibt
          erhalten.{" "}
          <Button
            type="button"
            variant="secondary"
            onClick={() => void epics.refetch()}
          >
            Erneut laden
          </Button>
        </StatusMessage>
      )}
      <div className="tasks-paging">
        <Button
          type="button"
          variant="secondary"
          disabled={offset === 0 || epics.isFetching}
          onClick={() => setOffset(Math.max(0, offset - 50))}
        >
          Vorherige Epics
        </Button>
        <Button
          type="button"
          variant="secondary"
          disabled={epics.data?.nextOffset == null || epics.isFetching}
          onClick={() => setOffset(epics.data!.nextOffset!)}
        >
          Weitere Epics
        </Button>
      </div>
      <label>
        Epic-Titel
        <input
          value={title}
          maxLength={240}
          onChange={(event) => {
            setTitle(event.target.value);
            operation.current = crypto.randomUUID();
            save.reset();
          }}
        />
      </label>
      <p>
        Ein Epic bündelt Aufgaben dieser Liste. Anlegen und Umbenennen werden
        sofort gespeichert, unabhängig vom Aufgabenentwurf.
      </p>
      {save.error && (
        <StatusMessage tone="error">
          {save.error instanceof ApiError && save.error.status === 409
            ? "Das Epic wurde inzwischen geändert. Lade die Epics neu und prüfe den Titel vor einem weiteren Versuch."
            : "Das Epic konnte nicht gespeichert werden. Prüfe deine Berechtigung und Verbindung."}
        </StatusMessage>
      )}
      {save.error && (
        <Button
          type="button"
          variant="secondary"
          onClick={() => {
            operation.current = crypto.randomUUID();
            save.reset();
            void epics.refetch();
          }}
        >
          Epics neu laden
        </Button>
      )}
      <div className="tasks-paging">
        <Button
          type="button"
          variant="secondary"
          disabled={!title.trim()}
          onClick={() => save.mutate(false)}
        >
          Epic anlegen
        </Button>
        <Button
          type="button"
          variant="secondary"
          disabled={!title.trim() || !selected || epics.isFetching}
          onClick={() => save.mutate(true)}
        >
          Ausgewähltes Epic umbenennen
        </Button>
      </div>
    </fieldset>
  );
}
