import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { LeonAidApiClient } from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

import { says, type Address } from "./task-copy";

export function AssigneePicker({
  address = "du",
  client,
  listId,
  value,
  userId,
  onChange,
}: {
  address?: Address;
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
    <fieldset className="task-fields task-picker">
      <legend className="sr-only">Zuständigkeit</legend>
      <label className="field">
        <span className="field-label">Personen suchen</span>
        <input
          className="input"
          type="search"
          maxLength={200}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setOffset(0);
          }}
        />
      </label>
      <label className="field">
        <span className="field-label">Zuständige Person</span>
        <select
          className="input select"
          value={value}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="">Nicht zugewiesen</option>
          {value && !selected && (
            <option value={value}>
              {value === userId
                ? says(address, "Ich", "Ich selbst")
                : "Bisherige zuständige Person"}
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
        <p className="field-hint" role="status">
          Berechtigte Personen werden geladen …
        </p>
      )}
      {people.error && (
        <StatusMessage tone="error">
          {says(
            address,
            "Die Personenauswahl ist nicht verfügbar. Prüfe deine Verbindung und dein Schreibrecht auf diese Liste. Eine bestehende Zuordnung bleibt erhalten.",
            "Die Personenauswahl ist nicht verfügbar. Prüfen Sie Ihre Verbindung und Ihr Schreibrecht auf diese Liste. Eine bestehende Zuordnung bleibt erhalten.",
          )}{" "}
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={() => void people.refetch()}
          >
            Personen neu laden
          </Button>
        </StatusMessage>
      )}
      {people.data?.items.length === 0 && (
        <p className="field-hint">
          Keine berechtigten Personen für diese Suche.
        </p>
      )}
      <div className="task-form-actions">
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={offset === 0 || people.isFetching}
          onClick={() => setOffset(Math.max(0, offset - 50))}
        >
          Vorherige Personen
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={people.data?.nextOffset == null || people.isFetching}
          onClick={() => setOffset(people.data!.nextOffset!)}
        >
          Weitere Personen
        </Button>
      </div>
    </fieldset>
  );
}
