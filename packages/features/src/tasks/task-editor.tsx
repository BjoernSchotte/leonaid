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
import { says, type Address } from "./task-copy";

export type Task = Awaited<ReturnType<LeonAidApiClient["getTask"]>>;

type PlanState = "scheduled" | "someday" | "unplanned";

export function TaskPlanPanel({
  address = "du",
  client,
  taskId,
}: {
  address?: Address;
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
  const [state, setState] = useState<PlanState>("unplanned");
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
      className="task-form task-plan"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <h3 className="task-form-title">Persönliche Planung</h3>
      <p className="field-hint">
        {says(
          address,
          "Nur du siehst diese Einordnung. Teamtermine bleiben unverändert.",
          "Nur Sie sehen diese Einordnung. Teamtermine bleiben unverändert.",
        )}
      </p>
      {plan.isPending ? (
        <p className="field-hint" role="status">
          Planung wird geladen …
        </p>
      ) : plan.isError ? (
        <StatusMessage tone="error">
          <p>Die persönliche Planung konnte nicht geladen werden.</p>
        </StatusMessage>
      ) : (
        <fieldset className="task-fields" disabled={save.isPending}>
          <label className="field">
            <span className="field-label">Einordnung</span>
            <select
              className="input select"
              value={state}
              onChange={(event) => {
                setState(event.target.value as PlanState);
                changed();
              }}
            >
              <option value="unplanned">Nicht geplant</option>
              <option value="scheduled">An einem Tag</option>
              <option value="someday">Irgendwann</option>
            </select>
          </label>
          {state === "scheduled" && (
            <label className="field">
              <span className="field-label">Geplant für</span>
              <input
                className="input"
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
                  ? says(
                      address,
                      "Die Planung wurde inzwischen geändert. Schließe die Aufgabe und öffne sie erneut.",
                      "Die Planung wurde inzwischen geändert. Schließen Sie die Aufgabe und öffnen Sie sie erneut.",
                    )
                  : "Die persönliche Planung konnte nicht gespeichert werden."}
              </p>
            </StatusMessage>
          )}
          {save.isSuccess && (
            <p className="field-hint" role="status">
              Planung gespeichert.
            </p>
          )}
          <div className="task-form-actions">
            <Button
              type="submit"
              variant="secondary"
              disabled={state === "scheduled" && !plannedOn}
              loading={save.isPending}
            >
              {save.isPending ? "Wird gespeichert …" : "Planung speichern"}
            </Button>
          </div>
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
  address = "du",
  client,
  listId,
  task,
  userId,
  onClose,
  onSaved,
  createTask,
  conflictMessage,
  onDirtyChange,
  closeOnEscape = true,
  headingLevel = 2,
}: {
  address?: Address;
  client: LeonAidApiClient;
  listId: string;
  task?: Task;
  userId: string;
  /** "Abbrechen", Escape and, without `onSaved`, a successful save. */
  onClose: () => void;
  /** A successful save; defaults to `onClose`. */
  onSaved?: () => void;
  conflictMessage?: string;
  onDirtyChange?: (dirty: boolean) => void;
  createTask?: (
    command: Parameters<LeonAidApiClient["createTask"]>[1],
  ) => Promise<Task>;
  /** In the list pane Escape belongs to the list (leave field, close pane). */
  closeOnEscape?: boolean;
  headingLevel?: 2 | 3;
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
  // Unmounting with a draft (pane closed, row gone) leaves no stale flag.
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);
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
      onDirtyChange?.(false);
      await cache.invalidateQueries({ queryKey: ["tasks"] });
      (onSaved ?? onClose)();
    },
  });
  const Heading = headingLevel === 3 ? "h3" : "h2";
  return (
    <form
      className="task-form task-editor"
      aria-labelledby={`${id}-heading`}
      onKeyDown={(event) => {
        if (!closeOnEscape || event.key !== "Escape") return;
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
      <Heading className="task-form-title" id={`${id}-heading`}>
        {task ? "Aufgabe bearbeiten" : "Neue Aufgabe"}
      </Heading>
      {save.error && (
        <StatusMessage tone="error">
          <p>
            {save.error instanceof ApiError && save.error.status === 409
              ? (conflictMessage ??
                says(
                  address,
                  "Die Aufgabe wurde inzwischen geändert oder dieser Speicherversuch hat einen Konflikt. Dein Entwurf bleibt erhalten. Schließe die Bearbeitung und lade die Aufgaben neu, bevor du deine Änderungen erneut übernimmst.",
                  "Die Aufgabe wurde inzwischen geändert oder dieser Speicherversuch hat einen Konflikt. Ihr Entwurf bleibt erhalten. Schließen Sie die Bearbeitung und laden Sie die Aufgaben neu, bevor Sie Ihre Änderungen erneut übernehmen.",
                ))
              : save.error instanceof ApiError &&
                  [403, 404].includes(save.error.status)
                ? says(
                    address,
                    "Du darfst diese Aufgabe nicht bearbeiten oder hast keinen Zugriff mehr auf die Liste.",
                    "Sie dürfen diese Aufgabe nicht bearbeiten oder haben keinen Zugriff mehr auf die Liste.",
                  )
                : says(
                    address,
                    "Speichern fehlgeschlagen. Dein Entwurf bleibt erhalten; du kannst erneut speichern.",
                    "Speichern fehlgeschlagen. Ihr Entwurf bleibt erhalten; Sie können erneut speichern.",
                  )}
          </p>
        </StatusMessage>
      )}
      <fieldset
        className="task-fields"
        disabled={save.isPending || epicPending}
      >
        <label className="field">
          <span className="field-label">Titel</span>
          <input
            className="input"
            autoFocus={!task}
            required
            maxLength={240}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        <label className="field">
          <span className="field-label">Beschreibung</span>
          <textarea
            className="input textarea"
            rows={4}
            maxLength={10000}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        {task && (
          <label className="field">
            <span className="field-label">Status</span>
            <select
              className="input select"
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
            address={address}
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
            address={address}
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
            <label className="field">
              <span className="field-label">Fällig am</span>
              <input
                className="input"
                type="datetime-local"
                value={due}
                onChange={(event) => setDue(event.target.value)}
              />
            </label>
            <label className="field">
              <span className="field-label">Zurückgestellt bis</span>
              <input
                className="input"
                type="datetime-local"
                value={deferred}
                onChange={(event) => setDeferred(event.target.value)}
              />
            </label>
          </div>
          <p className="field-hint">
            {says(
              address,
              "Zeiten gelten in deiner lokalen Zeitzone. Zurückstellen blendet die Aufgabe bis zu diesem Zeitpunkt aus; die Fälligkeit bleibt erhalten.",
              "Zeiten gelten in Ihrer lokalen Zeitzone. Zurückstellen blendet die Aufgabe bis zu diesem Zeitpunkt aus; die Fälligkeit bleibt erhalten.",
            )}
          </p>
        </details>
        <div className="task-form-actions">
          <Button
            type="submit"
            disabled={!title.trim()}
            loading={save.isPending}
          >
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
