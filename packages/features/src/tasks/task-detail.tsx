import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  CalendarDays,
  Eye,
  FolderInput,
} from "lucide-react";
import { useEffect, useState } from "react";
import { ApiError, type LeonAidApiClient } from "@leonaid/api-client";
import {
  Avatar,
  Badge,
  Button,
  DetailProps,
  DetailSection,
  Icon,
  useOptionalToast,
} from "@leonaid/ui";

import { says, type Address } from "./task-copy";
import { TaskEditor, TaskPlanPanel } from "./task-editor";
import {
  formatDateTime,
  localIsoDate,
  relativeDay,
  type TaskRow,
} from "./task-model";
import { TaskStructurePanel } from "./task-structure";

/** How the pane may move this row (manual list order or my plan). */
export interface TaskMoveControls {
  readonly kind: "list" | "plan";
  readonly previous: TaskRow | null;
  readonly next: TaskRow | null;
  readonly pending: boolean;
  readonly up: () => void;
  readonly down: () => void;
  /** List order: move to the end of a section (null = without section). */
  readonly toEpic: (epicId: string | null) => void;
  /** My plan: move to the end of a day. */
  readonly toDay: (plannedOn: string) => void;
}

/**
 * The form state follows the row while it is not dirty; a draft keeps the
 * revision it started from, so a save after someone else's change is
 * refused instead of overwriting it.
 */
function useSnapshot(row: TaskRow, dirty: boolean) {
  const [snapshot, setSnapshot] = useState(row.task);
  useEffect(() => {
    if (!dirty && row.task.revision !== snapshot.revision) {
      setSnapshot(row.task);
    }
  }, [dirty, row.task, snapshot.revision]);
  return snapshot;
}

export function TaskDetail({
  address,
  basePath,
  client,
  close,
  listPage,
  move,
  row,
  userId,
}: {
  readonly address: Address;
  readonly basePath: string;
  readonly client: LeonAidApiClient;
  /** Closes the pane (the guard asks about a draft). */
  readonly close: () => void;
  /** Shown on a list page: no link to the list itself. */
  readonly listPage: boolean;
  readonly move: TaskMoveControls | null;
  readonly row: TaskRow;
  readonly userId: string;
}) {
  const { task } = row;
  const toast = useOptionalToast();
  const today = localIsoDate();
  const [editorDirty, setEditorDirty] = useState(false);
  const editorTask = useSnapshot(row, editorDirty);
  const [editorKey, setEditorKey] = useState(0);
  const dueDay = task.dueAt ? localIsoDate(new Date(task.dueAt)) : null;
  const overdue = row.dueBucket === "overdue";
  return (
    <div
      className="task-detail"
      data-task-id={task.id}
      data-testid="task-detail"
    >
      {!task.canEdit ? (
        <div className="callout task-readonly" role="note">
          <Icon icon={Eye} size={16} />
          <span>
            <strong>Nur lesen.</strong>{" "}
            {says(
              address,
              "Du kannst diese Aufgabe sehen und für dich planen; bearbeiten dürfen die Bearbeiterinnen und Bearbeiter der Liste.",
              "Sie können diese Aufgabe sehen und für sich planen; bearbeiten dürfen die Bearbeiterinnen und Bearbeiter der Liste.",
            )}
          </span>
        </div>
      ) : null}

      <DetailSection title="Details">
        <DetailProps
          items={[
            {
              label: "Liste",
              value: listPage ? (
                task.listTitle
              ) : (
                <a href={`${basePath}/${task.listId}`}>{task.listTitle}</a>
              ),
            },
            { label: "Aktion", value: task.actionTitle ?? "Eigenständig" },
            {
              label: "Abschnitt",
              value: task.epicTitle ?? (
                <span className="subtle">Ohne Abschnitt</span>
              ),
            },
            {
              label: "Fällig",
              value:
                task.dueAt && dueDay ? (
                  <span className={overdue ? "task-overdue" : undefined}>
                    <time dateTime={task.dueAt}>
                      {formatDateTime(task.dueAt)}
                    </time>{" "}
                    <span className="subtle">
                      · {relativeDay(dueDay, today)}
                    </span>
                    {overdue ? (
                      <span className="sr-only"> (überfällig)</span>
                    ) : null}
                  </span>
                ) : (
                  <span className="subtle">Ohne Datum</span>
                ),
            },
            ...(task.deferredUntil
              ? [
                  {
                    label: "Zurückgestellt bis",
                    value: (
                      <time dateTime={task.deferredUntil}>
                        {formatDateTime(task.deferredUntil)}
                      </time>
                    ),
                  },
                ]
              : []),
            {
              label: "Schlagworte",
              value: task.tags.length ? (
                <span className="cluster">
                  {task.tags.map((tag) => (
                    <Badge key={tag.id}>{tag.title}</Badge>
                  ))}
                </span>
              ) : (
                <span className="subtle">Keine</span>
              ),
            },
          ]}
        />
      </DetailSection>

      {task.description ? (
        <DetailSection title="Beschreibung">
          <p className="task-description">{task.description}</p>
        </DetailSection>
      ) : null}

      <TaskSteps address={address} client={client} row={row} />

      {task.canEdit ? <ListAudience client={client} row={row} /> : null}

      {move ? (
        <TaskMoveSection
          address={address}
          client={client}
          move={move}
          row={row}
        />
      ) : null}

      {task.canEdit ? (
        <>
          <section className="pane-section">
            <TaskEditor
              address={address}
              client={client}
              closeOnEscape={false}
              headingLevel={3}
              key={`${editorTask.id}:${editorTask.revision}:${editorKey}`}
              listId={task.listId}
              // The list asks "Entwurf verwerfen?" when the form holds a
              // draft (useLeaveGuard in the pane).
              onClose={close}
              onDirtyChange={setEditorDirty}
              onSaved={() => {
                // The saved revision arrives with the refetched row.
                toast?.show({ title: "Aufgabe gespeichert.", tone: "success" });
                setEditorKey((key) => key + 1);
              }}
              task={editorTask}
              userId={userId}
            />
          </section>
          <section className="pane-section">
            <TaskStructurePanel address={address} client={client} task={task} />
          </section>
        </>
      ) : null}

      <section className="pane-section">
        <TaskPlanPanel address={address} client={client} taskId={task.id} />
      </section>
    </div>
  );
}

/** Checklist with direct toggles, as in the prototype's "Schritte". */
function TaskSteps({
  address,
  client,
  row,
}: {
  readonly address: Address;
  readonly client: LeonAidApiClient;
  readonly row: TaskRow;
}) {
  const { task } = row;
  const cache = useQueryClient();
  const toast = useOptionalToast();
  const toggle = useMutation({
    mutationFn: (stepId: string) =>
      client.setTaskStructure(task.id, {
        idempotencyKey: crypto.randomUUID(),
        expectedRevision: task.revision,
        priority: task.priority,
        tagIds: task.tags.map((tag) => tag.id),
        checklist: task.checklist.map((step) =>
          step.id === stepId ? { ...step, done: !step.done } : step,
        ),
      }),
    onError: (error) =>
      toast?.show({
        title: "Der Schritt wurde nicht gespeichert.",
        description:
          error instanceof ApiError && error.status === 409
            ? "Die Aufgabe wurde inzwischen geändert. Die Liste lädt den aktuellen Stand."
            : says(
                address,
                "Bitte versuche es erneut.",
                "Bitte versuchen Sie es erneut.",
              ),
        tone: "error",
      }),
    onSettled: () => cache.invalidateQueries({ queryKey: ["tasks"] }),
  });
  const done = task.checklist.filter((step) => step.done).length;
  return (
    <DetailSection
      title={
        <>
          Schritte{" "}
          {task.checklist.length ? (
            <span className="num">
              · {done} von {task.checklist.length}
            </span>
          ) : null}
        </>
      }
    >
      {task.checklist.length === 0 ? (
        <p className="small subtle">Noch keine Schritte.</p>
      ) : (
        <ul className="steps">
          {task.checklist.map((step) => (
            <li key={step.id}>
              <label className="checkbox">
                <input
                  checked={step.done}
                  disabled={!task.canEdit || toggle.isPending}
                  onChange={() => toggle.mutate(step.id)}
                  type="checkbox"
                />
                <span className={step.done ? "is-struck" : undefined}>
                  {step.text}
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}
    </DetailSection>
  );
}

function TaskMoveSection({
  address,
  client,
  move,
  row,
}: {
  readonly address: Address;
  readonly client: LeonAidApiClient;
  readonly move: TaskMoveControls;
  readonly row: TaskRow;
}) {
  const epics = useQuery({
    queryKey: ["task-epics", row.task.listId, "ordering"],
    queryFn: () => client.listTaskEpics(row.task.listId, { limit: 100 }),
    enabled: move.kind === "list",
    retry: false,
  });
  const [epic, setEpic] = useState(row.task.epicId ?? "");
  const [day, setDay] = useState(row.plan?.plannedOn ?? localIsoDate());
  return (
    <DetailSection title="Reihenfolge">
      <div className="task-move" role="group" aria-label="Reihenfolge ändern">
        <div className="cluster">
          <Button
            disabled={!move.previous || move.pending}
            icon={ArrowUp}
            onClick={move.up}
            size="sm"
            variant="secondary"
          >
            Nach oben
          </Button>
          <Button
            disabled={!move.next || move.pending}
            icon={ArrowDown}
            onClick={move.down}
            size="sm"
            variant="secondary"
          >
            Nach unten
          </Button>
        </div>
        {move.kind === "list" ? (
          <form
            className="task-move-form"
            onSubmit={(event) => {
              event.preventDefault();
              move.toEpic(epic || null);
            }}
          >
            <label className="field">
              <span className="field-label">In Abschnitt</span>
              <select
                className="input select"
                disabled={epics.isPending}
                onChange={(event) => setEpic(event.target.value)}
                value={epic}
              >
                <option value="">Ohne Abschnitt</option>
                {epics.data?.items.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title}
                  </option>
                ))}
              </select>
            </label>
            <Button
              disabled={move.pending || epics.isPending}
              icon={FolderInput}
              size="sm"
              type="submit"
              variant="secondary"
            >
              Verschieben
            </Button>
          </form>
        ) : (
          <form
            className="task-move-form"
            onSubmit={(event) => {
              event.preventDefault();
              if (day) move.toDay(day);
            }}
          >
            <label className="field">
              <span className="field-label">Für Tag planen</span>
              <input
                className="input"
                onChange={(event) => setDay(event.target.value)}
                required
                type="date"
                value={day}
              />
            </label>
            <Button
              disabled={move.pending}
              icon={CalendarDays}
              size="sm"
              type="submit"
              variant="secondary"
            >
              Planen
            </Button>
          </form>
        )}
        <p className="field-hint">
          {says(
            address,
            "Du kannst Aufgaben auch am Griff ziehen oder ihn mit der Leertaste aufnehmen und mit den Pfeiltasten bewegen.",
            "Sie können Aufgaben auch am Griff ziehen oder ihn mit der Leertaste aufnehmen und mit den Pfeiltasten bewegen.",
          )}
        </p>
      </div>
    </DetailSection>
  );
}

/** "Wer die Liste sieht": the list's members, for people who manage it. */
function ListAudience({
  client,
  row,
}: {
  readonly client: LeonAidApiClient;
  readonly row: TaskRow;
}) {
  const members = useQuery({
    queryKey: ["task-members", row.task.listId, "pane"],
    queryFn: () => client.listTaskListMembers(row.task.listId, { limit: 20 }),
    retry: false,
    staleTime: 60_000,
    // Editors who do not manage the list get a 403. The API has no manage
    // flag to ask first, so the refusal is kept for the visit: one request
    // per list, not one per opened task.
    gcTime: Number.POSITIVE_INFINITY,
    retryOnMount: false,
    refetchOnWindowFocus: false,
  });
  // Only list managers may read members; others simply do not see this.
  if (members.isError || !members.data) return null;
  const items = members.data.items.filter((member) => member.active);
  // No extra members: the list is visible to its owner (and, for an action
  // list, the action's members) only; an empty section would say nothing.
  if (items.length === 0 && !row.task.actionTitle) return null;
  return (
    <DetailSection title="Wer die Liste sieht">
      {items.length === 0 ? (
        <p className="small subtle">Keine weiteren Mitglieder.</p>
      ) : null}
      <ul className="access-list">
        {items.map((member) => (
          <li key={member.userId}>
            <Avatar name={member.displayName} size="xs" />
            <span>{member.displayName}</span>
            <Badge tone={member.access === "editor" ? "zone" : "neutral"}>
              {member.access === "editor" ? "Bearbeiten" : "Lesen"}
            </Badge>
          </li>
        ))}
      </ul>
      {row.task.actionTitle ? (
        <p className="small subtle">
          Dazu die Mitglieder der Aktion „{row.task.actionTitle}“.
        </p>
      ) : null}
      {members.data.nextOffset !== null ? (
        <p className="small subtle">
          Weitere Mitglieder unter „Zugriff verwalten“.
        </p>
      ) : null}
    </DetailSection>
  );
}
