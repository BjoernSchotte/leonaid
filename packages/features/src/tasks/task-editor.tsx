import {
  useIsMutating,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { ApiError, type LeonAidApiClient } from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

import { AssigneePicker } from "./assignee-picker";
import { EpicPicker } from "./epic-picker";

export type Task = Awaited<ReturnType<LeonAidApiClient["getTask"]>>;

export function TaskPlanPanel({
  client,
  taskId,
}: {
  client: LeonAidApiClient;
  taskId: string;
}) {
  const cache = useQueryClient();
  const operation = useRef(crypto.randomUUID());
  const plan = useQuery({
    queryKey: ["task-plan", taskId],
    queryFn: () => client.getTaskPlan(taskId),
    retry: false,
  });
  const [state, setState] = useState<"scheduled" | "someday" | "unplanned">(
    "unplanned",
  );
  const [plannedOn, setPlannedOn] = useState("");
  useEffect(() => {
    if (!plan.data) return;
    setState(plan.data.state);
    setPlannedOn(plan.data.plannedOn ?? "");
  }, [plan.data]);
  const save = useMutation({
    mutationFn: () =>
      client.setTaskPlan(taskId, {
        idempotencyKey: operation.current,
        expectedRevision: plan.data?.revision ?? 0,
        state,
        plannedOn: state === "scheduled" ? plannedOn : null,
      }),
    onSuccess: async (saved) => {
      cache.setQueryData(["task-plan", taskId], saved);
      operation.current = crypto.randomUUID();
      await cache.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
  const changed = () => {
    operation.current = crypto.randomUUID();
    save.reset();
  };
  return (
    <form
      className="task-plan"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <h2>Persönliche Planung</h2>
      <p>Nur du siehst diese Einordnung. Teamtermine bleiben unverändert.</p>
      {plan.isPending ? (
        <p role="status">Planung wird geladen …</p>
      ) : plan.isError ? (
        <StatusMessage tone="error">
          <p>Die persönliche Planung konnte nicht geladen werden.</p>
        </StatusMessage>
      ) : (
        <fieldset disabled={save.isPending}>
          <label>
            Einordnung
            <select
              value={state}
              onChange={(event) => {
                setState(
                  event.target.value as "scheduled" | "someday" | "unplanned",
                );
                changed();
              }}
            >
              <option value="unplanned">Nicht geplant</option>
              <option value="scheduled">An einem Tag</option>
              <option value="someday">Irgendwann</option>
            </select>
          </label>
          {state === "scheduled" && (
            <label>
              Geplant für
              <input
                type="date"
                required
                value={plannedOn}
                onChange={(event) => {
                  setPlannedOn(event.target.value);
                  changed();
                }}
              />
            </label>
          )}
          {save.error && (
            <StatusMessage tone="error">
              <p>
                {save.error instanceof ApiError && save.error.status === 409
                  ? "Die Planung wurde inzwischen geändert. Schließe die Aufgabe und öffne sie erneut."
                  : "Die persönliche Planung konnte nicht gespeichert werden."}
              </p>
            </StatusMessage>
          )}
          {save.isSuccess && <p role="status">Planung gespeichert.</p>}
          <Button type="submit" disabled={state === "scheduled" && !plannedOn}>
            {save.isPending ? "Wird gespeichert …" : "Planung speichern"}
          </Button>
        </fieldset>
      )}
    </form>
  );
}

function localTime(value: string | null | undefined) {
  if (!value) return "";
  const date = new Date(value);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}T${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

export function TaskEditor({
  client,
  listId,
  task,
  userId,
  onClose,
  createTask,
  conflictMessage,
  onDirtyChange,
}: {
  client: LeonAidApiClient;
  listId: string;
  task?: Task;
  userId: string;
  onClose: () => void;
  conflictMessage?: string;
  onDirtyChange?: (dirty: boolean) => void;
  createTask?: (
    command: Parameters<LeonAidApiClient["createTask"]>[1],
  ) => Promise<Task>;
}) {
  const id = useId();
  const cache = useQueryClient();
  const epicPending =
    useIsMutating({ mutationKey: ["task-epic-write", listId] }) > 0;
  const operation = useRef(crypto.randomUUID());
  const [title, setTitle] = useState(task?.title ?? "");
  const [description, setDescription] = useState(task?.description ?? "");
  const [status, setStatus] = useState<"open" | "done">(task?.status ?? "open");
  const [epic, setEpic] = useState(task?.epicId ?? "");
  const [assignee, setAssignee] = useState(task?.assigneeUserId ?? "");
  const [due, setDue] = useState(localTime(task?.dueAt));
  const [deferred, setDeferred] = useState(localTime(task?.deferredUntil));
  const dirty =
    title !== (task?.title ?? "") ||
    description !== (task?.description ?? "") ||
    status !== (task?.status ?? "open") ||
    epic !== (task?.epicId ?? "") ||
    assignee !== (task?.assigneeUserId ?? "") ||
    due !== localTime(task?.dueAt) ||
    deferred !== localTime(task?.deferredUntil);
  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => {
    if (!dirty) return;
    const prevent = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", prevent);
    return () => window.removeEventListener("beforeunload", prevent);
  }, [dirty]);
  const save = useMutation({
    mutationFn: () => {
      const body = {
        title: title.trim(),
        description,
        assigneeUserId: assignee || null,
        epicId: epic || null,
        dueAt:
          due === localTime(task?.dueAt)
            ? (task?.dueAt ?? null)
            : due
              ? new Date(due).toISOString()
              : null,
        deferredUntil:
          deferred === localTime(task?.deferredUntil)
            ? (task?.deferredUntil ?? null)
            : deferred
              ? new Date(deferred).toISOString()
              : null,
        idempotencyKey: operation.current,
      };
      return task
        ? client.updateTask(task.id, {
            ...body,
            status,
            expectedRevision: task.revision,
          })
        : createTask
          ? createTask(body)
          : client.createTask(listId, body);
    },
    onSuccess: async () => {
      await cache.invalidateQueries({ queryKey: ["tasks"] });
      onDirtyChange?.(false);
      onClose();
    },
  });
  return (
    <form
      className="task-editor"
      aria-labelledby={`${id}-heading`}
      onKeyDown={(event) => {
        if (event.key !== "Escape") return;
        event.preventDefault();
        onClose();
      }}
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
      onChange={() => {
        operation.current = crypto.randomUUID();
        save.reset();
      }}
    >
      <h2 id={`${id}-heading`}>
        {task ? "Aufgabe bearbeiten" : "Neue Aufgabe"}
      </h2>
      {save.error && (
        <StatusMessage tone="error">
          <p>
            {save.error instanceof ApiError && save.error.status === 409
              ? (conflictMessage ??
                "Die Aufgabe wurde inzwischen geändert oder dieser Speicherversuch hat einen Konflikt. Dein Entwurf bleibt erhalten. Schließe die Bearbeitung und lade die Aufgaben neu, bevor du deine Änderungen erneut übernimmst.")
              : save.error instanceof ApiError &&
                  [403, 404].includes(save.error.status)
                ? "Du darfst diese Aufgabe nicht bearbeiten oder hast keinen Zugriff mehr auf die Liste."
                : "Speichern fehlgeschlagen. Dein Entwurf bleibt erhalten; du kannst erneut speichern."}
          </p>
        </StatusMessage>
      )}
      <fieldset disabled={save.isPending || epicPending}>
        <label>
          Titel
          <input
            autoFocus
            required
            maxLength={240}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        <label>
          Beschreibung
          <textarea
            rows={4}
            maxLength={10000}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        {task && (
          <label>
            Status
            <select
              value={status}
              onChange={(event) =>
                setStatus(event.target.value as "open" | "done")
              }
            >
              <option value="open">Offen</option>
              <option value="done">Erledigt</option>
            </select>
          </label>
        )}
        <details className="task-editor-property">
          <summary>Zuständigkeit auswählen</summary>
          <AssigneePicker
            client={client}
            listId={listId}
            value={assignee}
            userId={userId}
            onChange={(value) => {
              setAssignee(value);
              operation.current = crypto.randomUUID();
              save.reset();
            }}
          />
        </details>
        <details className="task-editor-property">
          <summary>Abschnitt auswählen</summary>
          <EpicPicker
            client={client}
            listId={listId}
            value={epic}
            onChange={(value) => {
              setEpic(value);
              operation.current = crypto.randomUUID();
              save.reset();
            }}
          />
        </details>
        <details className="task-editor-property">
          <summary>Termine und Wiedervorlage</summary>
          <div className="task-editor-dates">
            <label>
              Fällig am
              <input
                type="datetime-local"
                value={due}
                onChange={(event) => setDue(event.target.value)}
              />
            </label>
            <label>
              Zurückgestellt bis
              <input
                type="datetime-local"
                value={deferred}
                onChange={(event) => setDeferred(event.target.value)}
              />
            </label>
          </div>
          <p>
            Zeiten gelten in deiner lokalen Zeitzone. Zurückstellen blendet die
            Aufgabe bis zu diesem Zeitpunkt aus; die Fälligkeit bleibt erhalten.
          </p>
        </details>
        <div className="tasks-paging">
          <Button type="submit" disabled={!title.trim()}>
            {save.isPending ? "Wird gespeichert …" : "Speichern"}
          </Button>
          <Button variant="secondary" type="button" onClick={onClose}>
            Abbrechen
          </Button>
        </div>
      </fieldset>
    </form>
  );
}
