import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { LeonAidApiClient } from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

export function useActionContexts(client: LeonAidApiClient) {
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const query = useQuery({
    queryKey: ["task-action-contexts", search, offset],
    queryFn: () => client.listTaskActionContexts({ search, offset }),
    retry: false,
  });
  // This existing query exposes the same current action-management policy
  // used by both list and page creation; each write checks it again.
  const items = query.error ? [] : (query.data?.items ?? []);
  return {
    query,
    search,
    offset,
    setOffset,
    searchFor: (value: string) => {
      setSearch(value);
      setOffset(0);
    },
    knownActions: items.map(
      (action) => [action.actionId, action.name] as const,
    ),
    managedActions: items
      .filter((action) => action.canCreateLists)
      .map((action) => [action.actionId, action.name] as const),
  };
}

export function ActionContextSearch({
  contexts,
}: {
  contexts: ReturnType<typeof useActionContexts>;
}) {
  const { query, search, offset, searchFor, setOffset } = contexts;
  return (
    <details>
      <summary>Aktionen suchen</summary>
      <label>
        Aktionsname
        <input
          type="search"
          maxLength={200}
          value={search}
          onChange={(event) => searchFor(event.target.value)}
        />
      </label>
      {query.isPending && <p role="status">Aktionen werden geladen …</p>}
      {query.error && (
        <StatusMessage tone="error">
          Aktionen konnten nicht geladen werden.{" "}
          <Button variant="secondary" onClick={() => void query.refetch()}>
            Aktionen neu laden
          </Button>
        </StatusMessage>
      )}
      {!query.error && query.data?.items.length === 0 && (
        <p>Keine zugänglichen Aktionen für diese Suche.</p>
      )}
      <div>
        <Button
          variant="secondary"
          disabled={offset === 0 || query.isFetching}
          onClick={() => setOffset(Math.max(0, offset - 50))}
        >
          Vorherige Aktionen
        </Button>{" "}
        <Button
          variant="secondary"
          disabled={
            query.data?.nextOffset == null || query.isFetching || !!query.error
          }
          onClick={() => setOffset(query.data!.nextOffset!)}
        >
          Weitere Aktionen
        </Button>
      </div>
    </details>
  );
}
