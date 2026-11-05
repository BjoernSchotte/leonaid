import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Link as LinkIcon,
  ListChecks,
  RefreshCw,
  Unlink,
  X,
} from "lucide-react";
import { useRef, useState } from "react";

import {
  ApiError,
  type Case,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, Field, IconButton, Input, StatusMessage } from "@leonaid/ui";

import { acceptCases, type Address } from "./inbox-model";

export const taskReferencesKey = (caseId: string) => ["inbox-tasks", caseId];

export function useTaskReferences(client: LeonAidApiClient, caseId: string) {
  return useQuery({
    queryKey: taskReferencesKey(caseId),
    queryFn: () => client.listInboxTaskReferences(caseId),
    retry: false,
    refetchInterval: 30000,
  });
}

function changeError(error: unknown, address: Address) {
  if (error instanceof ApiError && error.status === 409)
    return address === "Sie"
      ? "Die Anfrage wurde inzwischen geändert. Prüfen Sie die aktuellen Verweise und wiederholen Sie Ihre Auswahl."
      : "Die Anfrage wurde inzwischen geändert. Prüfe die aktuellen Verweise und wiederhole deine Auswahl.";
  return address === "Sie"
    ? "Der Aufgabenverweis konnte nicht geändert werden. Prüfen Sie Ihren Zugriff und versuchen Sie es erneut."
    : "Der Aufgabenverweis konnte nicht geändert werden. Prüfe deinen Zugriff und versuche es erneut.";
}

/**
 * Task references of a case as reference chips, plus the picker. The chips
 * show the current task status; the tasks keep their own access rules.
 */
export function InboxTasks({
  address,
  client,
  item,
  taskBasePath,
}: {
  readonly address: Address;
  readonly client: LeonAidApiClient;
  readonly item: Case;
  readonly taskBasePath: string;
}) {
  const cache = useQueryClient();
  const [picking, setPicking] = useState(false);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const pending = useRef<{ signature: string; key: string } | null>(null);
  const references = useTaskReferences(client, item.id);
  const tasks = useQuery({
    queryKey: ["tasks", "inbox-picker", search, offset],
    queryFn: () =>
      client.listTasks({ search, offset, limit: 25, includeDeferred: true }),
    enabled: picking,
    retry: false,
  });
  const change = useMutation({
    mutationFn: ({ taskId, present }: { taskId: string; present: boolean }) => {
      const signature = JSON.stringify([taskId, present, item.revision]);
      if (pending.current?.signature !== signature)
        pending.current = { signature, key: crypto.randomUUID() };
      return client.setInboxTaskReference(item.id, {
        taskId,
        present,
        expectedRevision: item.revision,
        idempotencyKey: pending.current.key,
      });
    },
    onSuccess: (value) => {
      acceptCases(cache, [value]);
      void cache.invalidateQueries({ queryKey: taskReferencesKey(item.id) });
      pending.current = null;
      setPicking(false);
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409)
        void cache.invalidateQueries({ queryKey: ["inbox-cases"] });
    },
  });
  const linked = new Set(
    references.data?.items.map((reference) => reference.taskId) ?? [],
  );
  return (
    <>
      {references.error ? (
        <StatusMessage tone="error">
          <p>Aufgabenverweise konnten nicht geladen werden.</p>
          <Button
            icon={RefreshCw}
            onClick={() => void references.refetch()}
            size="sm"
            variant="secondary"
          >
            Aufgabenverweise erneut laden
          </Button>
        </StatusMessage>
      ) : null}
      {references.data?.items.map((reference) => {
        const title = reference.task?.title ?? "Aufgabe nicht verfügbar";
        const state = reference.task?.status === "done" ? "Erledigt" : "Offen";
        return (
          <span className="ref-item" key={reference.taskId}>
            {reference.task ? (
              <a
                className="ref-chip"
                // Same deep link as the tasks module search: the list in
                // "Alle" with this task's detail open.
                href={`${taskBasePath}/${reference.task.listId}?view=all&open=${encodeURIComponent(reference.taskId)}`}
                title="Aufgabe öffnen"
              >
                <ListChecks aria-hidden="true" size={13} />
                {title} · {state}
              </a>
            ) : (
              <span className="ref-chip is-missing">
                <ListChecks aria-hidden="true" size={13} />
                {title}
              </span>
            )}
            <IconButton
              disabled={change.isPending}
              icon={Unlink}
              label={`Aufgabenverweis entfernen: ${title}`}
              onClick={() =>
                change.mutate({ taskId: reference.taskId, present: false })
              }
              size="sm"
              variant="ghost"
            />
          </span>
        );
      })}
      <InboxLinkButton
        disabled={picking || change.isPending}
        label="Aufgabe verknüpfen"
        onClick={() => {
          setPicking(true);
          change.reset();
        }}
      />
      {picking ? (
        <fieldset className="inbox-picker" disabled={change.isPending}>
          <legend>Bestehende Aufgabe auswählen</legend>
          <Field id={`task-search-${item.id}`} label="Aufgabentitel suchen">
            <Input
              maxLength={200}
              onChange={(event) => {
                setSearch(event.target.value);
                setOffset(0);
              }}
              type="search"
              value={search}
            />
          </Field>
          {tasks.isPending ? (
            <p className="small subtle" role="status">
              Aufgaben werden geladen …
            </p>
          ) : null}
          {tasks.error ? (
            <StatusMessage tone="error">
              <p>Aufgaben konnten nicht geladen werden.</p>
              <Button
                icon={RefreshCw}
                onClick={() => void tasks.refetch()}
                size="sm"
                variant="secondary"
              >
                Aufgaben erneut laden
              </Button>
            </StatusMessage>
          ) : null}
          {!tasks.error && tasks.data ? (
            <>
              {tasks.data.items.length ? (
                <ul className="match-results">
                  {tasks.data.items.map((task) => (
                    <li key={task.id}>
                      <button
                        className="match-option"
                        disabled={linked.has(task.id)}
                        onClick={() =>
                          change.mutate({ taskId: task.id, present: true })
                        }
                        type="button"
                      >
                        <ListChecks aria-hidden="true" size={14} />
                        <span>
                          {task.title} ·{" "}
                          {task.status === "done" ? "Erledigt" : "Offen"}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="small subtle">
                  Keine passenden zugänglichen Aufgaben.
                </p>
              )}
              <div className="cluster">
                <Button
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - 25))}
                  size="sm"
                  variant="ghost"
                >
                  Vorherige Aufgaben
                </Button>
                <Button
                  disabled={tasks.data.nextOffset == null}
                  onClick={() => setOffset(tasks.data.nextOffset ?? offset)}
                  size="sm"
                  variant="ghost"
                >
                  Weitere Aufgaben
                </Button>
              </div>
            </>
          ) : null}
          <div className="cluster">
            <Button
              icon={X}
              onClick={() => setPicking(false)}
              size="sm"
              variant="ghost"
            >
              Aufgabenauswahl schließen
            </Button>
          </div>
        </fieldset>
      ) : null}
      {change.error ? (
        <StatusMessage tone="error">
          {changeError(change.error, address)}
        </StatusMessage>
      ) : null}
    </>
  );
}

export function InboxLinkButton({
  disabled,
  label,
  onClick,
}: {
  readonly disabled: boolean;
  readonly label: string;
  readonly onClick: () => void;
}) {
  return (
    <Button
      className="case-link-button"
      disabled={disabled}
      icon={LinkIcon}
      onClick={onClick}
      size="sm"
      variant="secondary"
    >
      {label}
    </Button>
  );
}
