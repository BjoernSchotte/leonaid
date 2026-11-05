import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { ApiError, type LeonAidApiClient } from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

import { says, type Address } from "./task-copy";

export function EpicPicker({
  address = "du",
  client,
  listId,
  value,
  onChange,
}: {
  address?: Address;
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
    <fieldset
      className="task-fields task-picker task-epic-picker"
      disabled={save.isPending}
    >
      <legend className="sr-only">Abschnitt (optional)</legend>
      <label className="field">
        <span className="field-label">Abschnitte suchen</span>
        <input
          className="input"
          type="search"
          value={search}
          maxLength={200}
          onChange={(event) => {
            setSearch(event.target.value);
            setOffset(0);
          }}
        />
      </label>
      <label className="field">
        <span className="field-label">Vorhandener Abschnitt</span>
        <select
          className="input select"
          value={value}
          onChange={(event) => {
            onChange(event.target.value);
            operation.current = crypto.randomUUID();
            save.reset();
          }}
        >
          <option value="">Ohne Abschnitt</option>
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
      {epics.isPending && (
        <p className="field-hint" role="status">
          Abschnitte werden geladen …
        </p>
      )}
      {epics.error && (
        <StatusMessage tone="error">
          Abschnitte konnten nicht geladen werden. Die aktuelle Zuordnung bleibt
          erhalten.{" "}
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={() => void epics.refetch()}
          >
            Erneut laden
          </Button>
        </StatusMessage>
      )}
      <div className="task-form-actions">
        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={offset === 0 || epics.isFetching}
          onClick={() => setOffset(Math.max(0, offset - 50))}
        >
          Vorherige Abschnitte
        </Button>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={epics.data?.nextOffset == null || epics.isFetching}
          onClick={() => setOffset(epics.data!.nextOffset!)}
        >
          Weitere Abschnitte
        </Button>
      </div>
      <label className="field">
        <span className="field-label">Titel des Abschnitts</span>
        <input
          className="input"
          value={title}
          maxLength={240}
          onChange={(event) => {
            setTitle(event.target.value);
            operation.current = crypto.randomUUID();
            save.reset();
          }}
        />
      </label>
      <p className="field-hint">
        Ein Abschnitt bündelt Aufgaben dieser Liste. Anlegen und Umbenennen
        werden sofort gespeichert, unabhängig vom Aufgabenentwurf.
      </p>
      {save.error && (
        <StatusMessage tone="error">
          {save.error instanceof ApiError && save.error.status === 409
            ? says(
                address,
                "Der Abschnitt wurde inzwischen geändert. Lade die Abschnitte neu und prüfe den Titel vor einem weiteren Versuch.",
                "Der Abschnitt wurde inzwischen geändert. Laden Sie die Abschnitte neu und prüfen Sie den Titel vor einem weiteren Versuch.",
              )
            : says(
                address,
                "Der Abschnitt konnte nicht gespeichert werden. Prüfe deine Berechtigung und Verbindung.",
                "Der Abschnitt konnte nicht gespeichert werden. Prüfen Sie Ihre Berechtigung und Verbindung.",
              )}
        </StatusMessage>
      )}
      {save.error && (
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={() => {
            operation.current = crypto.randomUUID();
            save.reset();
            void epics.refetch();
          }}
        >
          Abschnitte neu laden
        </Button>
      )}
      <div className="task-form-actions">
        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={!title.trim()}
          onClick={() => save.mutate(false)}
        >
          Abschnitt anlegen
        </Button>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={!title.trim() || !selected || epics.isFetching}
          onClick={() => save.mutate(true)}
        >
          Ausgewähltes Abschnitt umbenennen
        </Button>
      </div>
    </fieldset>
  );
}
