import { useMutation, useQuery } from "@tanstack/react-query";
import { useRef, useState, type ReactNode } from "react";
import { type LeonAidApiClient, type TaskList } from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

import {
  ActionContextSearch,
  useActionContexts,
} from "../shared/action-contexts";
import { ListMembersPanel } from "./list-members";
import { says, type Address } from "./task-copy";

function ToolPanel({
  children,
  heading,
  id,
  onClose,
}: {
  readonly children: ReactNode;
  readonly heading: string;
  readonly id: string;
  readonly onClose: () => void;
}) {
  return (
    <section aria-labelledby={`${id}-heading`} className="task-panel" id={id}>
      <div className="task-panel-heading">
        <h2 id={`${id}-heading`}>{heading}</h2>
        <Button onClick={onClose} size="sm" variant="ghost">
          Schließen
        </Button>
      </div>
      {children}
    </section>
  );
}

/** "Liste wechseln": all accessible lists, the action filter and "Neue Liste". */
export function TaskListNavigation({
  address,
  basePath,
  client,
  listId,
  onClose,
}: {
  readonly address: Address;
  readonly basePath: string;
  readonly client: LeonAidApiClient;
  readonly listId?: string;
  readonly onClose: () => void;
}) {
  const contexts = useActionContexts(client);
  const { knownActions, managedActions } = contexts;
  const [offset, setOffset] = useState(0);
  const [actionFilter, setActionFilter] = useState("");
  const [title, setTitle] = useState("");
  const [newActionId, setNewActionId] = useState("");
  const operation = useRef(crypto.randomUUID());
  const lists = useQuery({
    queryKey: ["task-lists", offset, actionFilter],
    queryFn: () =>
      client.listTaskLists({
        offset,
        actionId: actionFilter || undefined,
      }),
  });
  const create = useMutation({
    mutationFn: () =>
      client.createTaskList({
        title: title.trim(),
        actionId: newActionId || null,
        idempotencyKey: operation.current,
      }),
    onSuccess: (list) => window.location.assign(`${basePath}/${list.id}`),
  });
  return (
    <ToolPanel
      heading="Aufgabenliste wechseln"
      id="task-list-navigation"
      onClose={onClose}
    >
      <ActionContextSearch contexts={contexts} />
      {(knownActions.length > 0 || actionFilter) && (
        <label className="field">
          <span className="field-label">Listen nach Aktion filtern</span>
          <select
            className="input select"
            value={actionFilter}
            onChange={(event) => {
              setActionFilter(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">Alle zugänglichen Listen</option>
            {actionFilter &&
              !knownActions.some(([id]) => id === actionFilter) && (
                <option value={actionFilter}>
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
      <ul className="task-list-links">
        <li>
          <a aria-current={!listId ? "page" : undefined} href={basePath}>
            Alle zugänglichen Aufgaben
          </a>
        </li>
        {lists.data?.items.map((list) => (
          <li key={list.id}>
            <a
              aria-current={list.id === listId ? "page" : undefined}
              href={`${basePath}/${list.id}`}
            >
              {list.title}
            </a>
          </li>
        ))}
      </ul>
      {lists.isPending ? (
        <p className="small subtle" role="status">
          Listen werden geladen …
        </p>
      ) : null}
      {lists.isError ? (
        <StatusMessage tone="error">
          <p>Die Listen konnten nicht geladen werden.</p>
          <Button
            onClick={() => void lists.refetch()}
            size="sm"
            variant="secondary"
          >
            Erneut laden
          </Button>
        </StatusMessage>
      ) : null}
      {lists.data?.items.length === 0 && (
        <p className="small subtle">Noch keine Listen vorhanden.</p>
      )}
      <div className="cluster">
        <Button
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - 50))}
          size="sm"
          variant="ghost"
        >
          Vorherige Listen
        </Button>
        <Button
          disabled={lists.data?.nextOffset == null}
          onClick={() => setOffset(lists.data!.nextOffset!)}
          size="sm"
          variant="ghost"
        >
          Weitere Listen
        </Button>
      </div>
      <details className="task-new-list">
        <summary>Neue Liste</summary>
        <form
          className="task-fields"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate();
          }}
        >
          <label className="field">
            <span className="field-label">Kontext der neuen Liste</span>
            <select
              className="input select"
              value={newActionId}
              disabled={create.isPending}
              onChange={(event) => {
                setNewActionId(event.target.value);
                operation.current = crypto.randomUUID();
                create.reset();
              }}
            >
              <option value="">Eigenständig</option>
              {newActionId &&
                !managedActions.some(([id]) => id === newActionId) && (
                  <option value={newActionId}>
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
          <p className="field-hint">
            {newActionId
              ? "Aktuelle Mitglieder dieser Aktion können die Liste lesen. Die Aktionsverwaltung kann sie bearbeiten und zusätzliche Bearbeitungsrechte vergeben."
              : says(
                  address,
                  "Die Liste ist zunächst nur für dich sichtbar.",
                  "Die Liste ist zunächst nur für Sie sichtbar.",
                )}
          </p>
          <label className="field">
            <span className="field-label">Name der Liste</span>
            <input
              className="input"
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
          </label>
          {create.isError ? (
            <StatusMessage tone="error">
              <p>Die Liste konnte nicht angelegt werden.</p>
            </StatusMessage>
          ) : null}
          <div className="task-form-actions">
            <Button
              disabled={!title.trim()}
              loading={create.isPending}
              type="submit"
            >
              {create.isPending ? "Wird angelegt …" : "Liste anlegen"}
            </Button>
          </div>
        </form>
      </details>
    </ToolPanel>
  );
}

/** "Zugriff verwalten" of the current list (editors only). */
export function TaskListAccess({
  address,
  client,
  list,
  onClose,
}: {
  readonly address: Address;
  readonly client: LeonAidApiClient;
  readonly list: TaskList;
  readonly onClose: () => void;
}) {
  return (
    <ToolPanel
      heading="Zugriff verwalten"
      id="task-list-access"
      onClose={onClose}
    >
      <ListMembersPanel
        actionScoped={!!list.actionId}
        address={address}
        embedded
        client={client}
        listId={list.id}
      />
    </ToolPanel>
  );
}
