import {
  ArrowLeft01Icon,
  ArrowRight01Icon,
  Cancel01Icon,
  Link01Icon,
  RefreshIcon,
  Unlink01Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import {
  ApiError,
  type Case,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

export function InboxTasks({
  client,
  item,
  taskBasePath,
}: {
  client: LeonAidApiClient;
  item: Case;
  taskBasePath: string;
}) {
  const cache = useQueryClient();
  const [picking, setPicking] = useState(false);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [notice, setNotice] = useState("");
  const pending = useRef<{ signature: string; key: string } | null>(null);
  const references = useQuery({
    queryKey: ["inbox-tasks", item.id],
    queryFn: () => client.listInboxTaskReferences(item.id),
    retry: false,
    refetchInterval: 30000,
  });
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
      cache.setQueryData(["inbox-case", item.id], value);
      void cache.invalidateQueries({ queryKey: ["inbox-tasks", item.id] });
      void cache.invalidateQueries({ queryKey: ["inbox-cases"] });
      pending.current = null;
      setPicking(false);
      setNotice("Aufgabenverweise aktualisiert.");
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409)
        void cache.invalidateQueries({ queryKey: ["inbox-case", item.id] });
    },
  });
  return (
    <section aria-labelledby="inbox-tasks-heading">
      <h2 id="inbox-tasks-heading">Aufgaben</h2>
      <p>
        Verweise zeigen den aktuellen Aufgabenstatus. Die Zugriffsrechte der
        Aufgaben bleiben bestehen.
      </p>
      {references.isPending && (
        <p role="status">Aufgabenverweise werden geladen …</p>
      )}
      {references.error && (
        <StatusMessage tone="error">
          <p>Aufgabenverweise konnten nicht geladen werden.</p>
          <Button
            icon={
              <HugeiconsIcon
                icon={RefreshIcon}
                size={16}
                strokeWidth={1.7}
                aria-hidden="true"
              />
            }
            variant="secondary"
            onClick={() => void references.refetch()}
          >
            Aufgabenverweise erneut laden
          </Button>
        </StatusMessage>
      )}
      {!references.error && references.data && (
        <ul className="inbox-results">
          {references.data.items.map((reference) => (
            <li key={reference.taskId}>
              <p>
                {reference.task
                  ? `${reference.task.title} · ${reference.task.status === "done" ? "Erledigt" : "Offen"}`
                  : "Aufgabe nicht verfügbar"}
              </p>
              <div className="inbox-paging">
                {reference.task && (
                  <a href={`${taskBasePath}/${reference.task.listId}`}>
                    Aufgabenliste öffnen
                  </a>
                )}
                <Button
                  icon={
                    <HugeiconsIcon
                      icon={Unlink01Icon}
                      size={16}
                      strokeWidth={1.7}
                      aria-hidden="true"
                    />
                  }
                  variant="secondary"
                  disabled={change.isPending}
                  onClick={() => {
                    setNotice("");
                    change.mutate({ taskId: reference.taskId, present: false });
                  }}
                >
                  Aufgabenverweis entfernen
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {!references.error && references.data?.items.length === 0 && (
        <p>Noch keine Aufgaben verknüpft.</p>
      )}
      <Button
        icon={
          <HugeiconsIcon
            icon={Link01Icon}
            size={16}
            strokeWidth={1.7}
            aria-hidden="true"
          />
        }
        variant="secondary"
        disabled={picking || change.isPending}
        onClick={() => {
          setPicking(true);
          change.reset();
          setNotice("");
        }}
      >
        Aufgabe verknüpfen
      </Button>
      {picking && (
        <fieldset
          className="inbox-picker inbox-form"
          disabled={change.isPending}
        >
          <legend>Bestehende Aufgabe auswählen</legend>
          <label>
            Aufgabentitel suchen
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
          {tasks.isPending && <p role="status">Aufgaben werden geladen …</p>}
          {tasks.error && (
            <StatusMessage tone="error">
              <p>Aufgaben konnten nicht geladen werden.</p>
              <Button
                icon={
                  <HugeiconsIcon
                    icon={RefreshIcon}
                    size={16}
                    strokeWidth={1.7}
                    aria-hidden="true"
                  />
                }
                variant="secondary"
                onClick={() => void tasks.refetch()}
              >
                Aufgaben erneut laden
              </Button>
            </StatusMessage>
          )}
          {!tasks.error && tasks.data && (
            <>
              <ul className="inbox-results">
                {tasks.data.items.map((task) => (
                  <li key={task.id}>
                    <Button
                      variant="secondary"
                      disabled={references.data?.items.some(
                        (reference) => reference.taskId === task.id,
                      )}
                      onClick={() =>
                        change.mutate({ taskId: task.id, present: true })
                      }
                    >
                      {task.title} ·{" "}
                      {task.status === "done" ? "Erledigt" : "Offen"}
                    </Button>
                  </li>
                ))}
              </ul>
              {!tasks.data.items.length && (
                <p>Keine passenden zugänglichen Aufgaben.</p>
              )}
              <div className="inbox-paging">
                <Button
                  icon={
                    <HugeiconsIcon
                      icon={ArrowLeft01Icon}
                      size={16}
                      strokeWidth={1.7}
                      aria-hidden="true"
                    />
                  }
                  variant="secondary"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - 25))}
                >
                  Vorherige Aufgaben
                </Button>
                <Button
                  icon={
                    <HugeiconsIcon
                      icon={ArrowRight01Icon}
                      size={16}
                      strokeWidth={1.7}
                      aria-hidden="true"
                    />
                  }
                  variant="secondary"
                  disabled={tasks.data.nextOffset == null}
                  onClick={() => setOffset(tasks.data.nextOffset ?? offset)}
                >
                  Weitere Aufgaben
                </Button>
              </div>
            </>
          )}
          <Button
            icon={
              <HugeiconsIcon
                icon={Cancel01Icon}
                size={16}
                strokeWidth={1.7}
                aria-hidden="true"
              />
            }
            variant="secondary"
            onClick={() => setPicking(false)}
          >
            Aufgabenauswahl schließen
          </Button>
        </fieldset>
      )}
      {change.error && (
        <StatusMessage tone="error">
          <p>
            {change.error instanceof ApiError && change.error.status === 409
              ? "Der Fall wurde inzwischen geändert. Prüfe die aktuellen Verweise und wiederhole deine Auswahl."
              : "Der Aufgabenverweis konnte nicht geändert werden. Prüfe deinen Zugriff und versuche es erneut."}
          </p>
        </StatusMessage>
      )}
      {notice && <p role="status">{notice}</p>}
    </section>
  );
}
