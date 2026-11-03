import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { LeonAidApiClient } from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

export function AssigneePicker({
  client,
  listId,
  value,
  userId,
  onChange,
}: {
  client: LeonAidApiClient;
  listId: string;
  value: string;
  userId: string;
  onChange: (value: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const people = useQuery({
    queryKey: ["task-assignees", listId, search, offset],
    queryFn: () => client.listTaskAssignees(listId, { search, offset }),
    retry: false,
  });
  const selected = people.data?.items.find((person) => person.userId === value);
  return (
    <fieldset>
      <legend>Zuständigkeit</legend>
      <label>
        Personen suchen
        <input
          type="search"
          maxLength={200}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setOffset(0);
          }}
        />
      </label>
      <label>
        Zuständige Person
        <select
          value={value}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="">Nicht zugewiesen</option>
          {value && !selected && (
            <option value={value}>
              {value === userId ? "Ich" : "Bisherige zuständige Person"}
            </option>
          )}
          {people.data?.items.map((person) => (
            <option value={person.userId} key={person.userId}>
              {person.displayName}
              {person.userId === userId ? " (ich)" : ""}
            </option>
          ))}
        </select>
      </label>
      {people.isPending && (
        <p role="status">Berechtigte Personen werden geladen …</p>
      )}
      {people.error && (
        <StatusMessage tone="error">
          Die Personenauswahl ist nicht verfügbar. Prüfe deine Verbindung und
          dein Schreibrecht auf diese Liste. Eine bestehende Zuordnung bleibt
          erhalten.{" "}
          <Button
            type="button"
            variant="secondary"
            onClick={() => void people.refetch()}
          >
            Personen neu laden
          </Button>
        </StatusMessage>
      )}
      {people.data?.items.length === 0 && (
        <p>Keine berechtigten Personen für diese Suche.</p>
      )}
      <div className="tasks-paging">
        <Button
          type="button"
          variant="secondary"
          disabled={offset === 0 || people.isFetching}
          onClick={() => setOffset(Math.max(0, offset - 50))}
        >
          Vorherige Personen
        </Button>
        <Button
          type="button"
          variant="secondary"
          disabled={people.data?.nextOffset == null || people.isFetching}
          onClick={() => setOffset(people.data!.nextOffset!)}
        >
          Weitere Personen
        </Button>
      </div>
    </fieldset>
  );
}
