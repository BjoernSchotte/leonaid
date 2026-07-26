import {
  Calendar02Icon,
  ClockAlertIcon,
  NoteEditIcon,
  TelephoneIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import {
  ApiError,
  type AcquisitionActivityBoardResponse,
  type AcquisitionActivityWorkItemResponse,
  type CurrentIdentityResponse,
  type LeonAidApiClient,
  type RecordAcquisitionActivityRequest,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

interface ActivityWorkspaceProps {
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
}

const channelLabels = {
  email: "E-Mail",
  in_person: "Persönlich",
  phone: "Telefon",
} as const;

const outcomeLabels = {
  committed: "Zusage",
  declined: "Absage",
  follow_up: "Später nachfassen",
  interested: "Interesse",
  no_answer: "Nicht erreicht",
  reached: "Erreicht",
} as const;

function berlinDate(value: string, includeYear = true) {
  return new Intl.DateTimeFormat("de-DE", {
    day: "2-digit",
    month: "short",
    timeZone: "Europe/Berlin",
    ...(includeYear ? { year: "numeric" } : {}),
  }).format(new Date(value));
}

function berlinDateTime(value: string) {
  return new Intl.DateTimeFormat("de-DE", {
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    month: "short",
    timeZone: "Europe/Berlin",
  }).format(new Date(value));
}

function todayInBerlin() {
  return new Intl.DateTimeFormat("sv-SE", {
    day: "2-digit",
    month: "2-digit",
    timeZone: "Europe/Berlin",
    year: "numeric",
  }).format(new Date());
}

function errorCopy(error: unknown) {
  if (
    error instanceof ApiError &&
    error.detail.code === "assignment_revision_conflict"
  ) {
    return "Der Sponsor wurde parallel geändert. Die aktuelle Version wurde neu geladen; bitte prüfe das Ergebnis und speichere erneut.";
  }
  if (error instanceof ApiError && error.status === 403) {
    return "Du bist dieser Aktion nicht als Akquisiteur zugeordnet. Öffne eine eigene Aktion oder wende dich an den Charity-Admin.";
  }
  return "Die Aktivität konnte nicht gespeichert werden. Prüfe deine Verbindung und versuche es erneut.";
}

function reminderLabel(item: AcquisitionActivityWorkItemResponse) {
  if (item.urgency === "overdue") return "Überfällig";
  if (item.urgency === "today") return "Heute";
  return item.dueAt ? berlinDate(item.dueAt, false) : "";
}

function ActivityBoard({
  board,
  onSelect,
}: {
  readonly board: AcquisitionActivityBoardResponse;
  readonly onSelect: (assignmentId: string) => void;
}) {
  const reminders = board.workItems.filter(
    (item) => item.nextAction && item.dueAt,
  );
  const counts = {
    overdue: reminders.filter((item) => item.urgency === "overdue").length,
    today: reminders.filter((item) => item.urgency === "today").length,
    upcoming: reminders.filter((item) => item.urgency === "upcoming").length,
  };

  return (
    <>
      <div
        aria-label="Wiedervorlagen-Übersicht"
        className="acq-reminder-summary"
      >
        <div data-urgency="overdue">
          <strong data-testid="overdue-count">{counts.overdue}</strong>
          <span>Überfällig</span>
        </div>
        <div data-urgency="today">
          <strong data-testid="today-count">{counts.today}</strong>
          <span>Heute</span>
        </div>
        <div>
          <strong>{counts.upcoming}</strong>
          <span>Demnächst</span>
        </div>
      </div>

      {reminders.length > 0 ? (
        <div className="acq-reminder-list" data-testid="reminder-list">
          {reminders.map((item) => (
            <button
              className="acq-reminder"
              data-select-assignment={item.assignmentId}
              data-urgency={item.urgency}
              key={item.assignmentId}
              onClick={() => onSelect(item.assignmentId)}
              type="button"
            >
              <span aria-hidden="true" className="acq-reminder__dot" />
              <span className="acq-reminder__copy">
                <strong>{item.partyDisplayName}</strong>
                <span>{item.nextAction}</span>
              </span>
              <span className="acq-reminder__date">{reminderLabel(item)}</span>
            </button>
          ))}
        </div>
      ) : (
        <div className="acq-empty">
          <HugeiconsIcon
            aria-hidden="true"
            icon={ClockAlertIcon}
            size={22}
            strokeWidth={1.8}
          />
          <strong>Für heute ist alles erledigt</strong>
          <span>
            Plane beim nächsten Kontakt direkt einen Folgeschritt, damit nichts
            verloren geht.
          </span>
        </div>
      )}

      <div className="acq-timeline-heading">
        <div>
          <h2>Letzte Aktivitäten</h2>
          <p>
            Neueste Einträge zuerst; bestehende Einträge werden nicht
            überschrieben.
          </p>
        </div>
      </div>
      {board.activities.length > 0 ? (
        <div className="acq-timeline" data-testid="activity-timeline">
          {board.activities.map((activity) => (
            <article
              className="acq-timeline__entry"
              data-activity-id={activity.id}
              data-testid="activity-entry"
              key={activity.id}
            >
              <div className="acq-timeline__title">
                <strong>{activity.partyDisplayName}</strong>
                <time dateTime={activity.occurredAt}>
                  {berlinDateTime(activity.occurredAt)}
                </time>
              </div>
              <div className="acq-timeline__meta">
                <span>{outcomeLabels[activity.outcome]}</span>
                <span>{channelLabels[activity.channel]}</span>
                <span>{activity.actorDisplayName}</span>
              </div>
              {activity.note ? (
                <p className="acq-timeline__note">{activity.note}</p>
              ) : null}
              {activity.nextAction && activity.dueAt ? (
                <div className="acq-timeline__next">
                  <strong>Nächster Schritt</strong>
                  <span>
                    {activity.nextAction} · {berlinDate(activity.dueAt)}
                  </span>
                </div>
              ) : null}
            </article>
          ))}
        </div>
      ) : (
        <div className="acq-empty acq-empty--compact">
          <HugeiconsIcon
            aria-hidden="true"
            icon={NoteEditIcon}
            size={22}
            strokeWidth={1.8}
          />
          <strong>Noch kein Kontakt dokumentiert</strong>
          <span>Die erste gespeicherte Aktivität erscheint hier.</span>
        </div>
      )}
    </>
  );
}

export function ActivityWorkspace({
  client,
  identity,
}: ActivityWorkspaceProps) {
  const memberships = useMemo(
    () =>
      identity.actionMemberships.filter(
        (membership) => membership.role === "acquirer",
      ),
    [identity.actionMemberships],
  );
  const [actionId, setActionId] = useState(memberships[0]?.actionId ?? "");
  const [assignmentId, setAssignmentId] = useState(
    () => new URLSearchParams(window.location.search).get("assignment") ?? "",
  );
  const [note, setNote] = useState("");
  const [nextAction, setNextAction] = useState("");
  const [dueOn, setDueOn] = useState("");
  const [success, setSuccess] = useState("");
  const channelRef = useRef<HTMLSelectElement>(null);

  const board = useQuery({
    enabled: Boolean(actionId),
    queryFn: () => client.getAcquisitionActivityBoard(actionId, { limit: 50 }),
    queryKey: ["acquisition-activity-board", actionId],
  });

  useEffect(() => {
    const items = board.data?.workItems ?? [];
    if (!items.some((item) => item.assignmentId === assignmentId)) {
      setAssignmentId(items[0]?.assignmentId ?? "");
    }
  }, [assignmentId, board.data?.workItems]);

  const record = useMutation({
    mutationFn: ({
      body,
      selectedActionId,
    }: {
      body: RecordAcquisitionActivityRequest;
      selectedActionId: string;
    }) => client.recordAcquisitionActivity(selectedActionId, body),
    onError: () => {
      setSuccess("");
      void board.refetch();
    },
    onSuccess: async (result) => {
      setSuccess(
        `Aktivität für ${result.activity.partyDisplayName} wurde gespeichert.`,
      );
      setNote("");
      setNextAction("");
      setDueOn("");
      await board.refetch();
    },
  });

  const selected = board.data?.workItems.find(
    (item) => item.assignmentId === assignmentId,
  );
  const reminderPairComplete =
    (nextAction.trim().length === 0 && dueOn.length === 0) ||
    (nextAction.trim().length > 0 && dueOn.length > 0);

  function selectReminder(nextAssignmentId: string) {
    setAssignmentId(nextAssignmentId);
    channelRef.current?.focus();
    document
      .querySelector("#activity-form")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || !reminderPairComplete) return;
    const values = new FormData(event.currentTarget);
    record.mutate({
      body: {
        channel: values.get(
          "channel",
        ) as RecordAcquisitionActivityRequest["channel"],
        dueOn: dueOn || null,
        nextAction: nextAction.trim() || null,
        note: note.trim() || null,
        outcome: values.get(
          "outcome",
        ) as RecordAcquisitionActivityRequest["outcome"],
        partyId: selected.partyId,
        partyKind: selected.partyKind,
        revision: selected.revision,
      },
      selectedActionId: actionId,
    });
  }

  return (
    <div className="acq-page">
      <header className="acq-page__header">
        <p className="acq-eyebrow">Akquise-Verlauf</p>
        <h1>Aktivitäten &amp; Wiedervorlagen</h1>
        <p>
          Halte einen Kontakt fest und plane direkt, was als Nächstes passieren
          soll. Fällige Aufgaben bleiben dabei immer vorn.
        </p>
      </header>

      <div className="acq-activity-layout">
        <section
          aria-labelledby="activity-form-heading"
          className="acq-workflow"
        >
          <div className="acq-section-heading">
            <span aria-hidden="true" className="acq-section-heading__icon">
              <HugeiconsIcon icon={TelephoneIcon} size={20} strokeWidth={1.8} />
            </span>
            <div>
              <h2 id="activity-form-heading">Was ist passiert?</h2>
              <p>
                Dokumentiere nur die Information, die für die weitere Akquise
                nötig ist.
              </p>
            </div>
          </div>

          <form className="acq-form" id="activity-form" onSubmit={submit}>
            <div className="acq-field acq-field--wide">
              <label htmlFor="activity-action">Charity-Aktion</label>
              <p id="activity-action-help">
                Die Aktion bestimmt, welche eigenen Sponsoren zur Auswahl
                stehen.
              </p>
              <select
                aria-describedby="activity-action-help"
                id="activity-action"
                name="actionId"
                onChange={(event) => {
                  setActionId(event.target.value);
                  setSuccess("");
                }}
                value={actionId}
              >
                {memberships.map((membership) => (
                  <option key={membership.actionId} value={membership.actionId}>
                    {membership.actionName}
                  </option>
                ))}
              </select>
            </div>

            <div className="acq-field acq-field--wide">
              <label htmlFor="activity-party">Sponsor</label>
              <p id="activity-party-help">
                Nur aktuell dir zugeordnete Firmen und Kontakte werden
                angezeigt.
              </p>
              <select
                aria-describedby="activity-party-help"
                data-testid="activity-party"
                disabled={!board.data?.workItems.length}
                id="activity-party"
                name="party"
                onChange={(event) => setAssignmentId(event.target.value)}
                required
                value={assignmentId}
              >
                {board.data?.workItems.length ? (
                  board.data.workItems.map((item) => (
                    <option key={item.assignmentId} value={item.assignmentId}>
                      {item.partyDisplayName}
                      {item.city ? ` · ${item.city}` : ""}
                    </option>
                  ))
                ) : (
                  <option value="">Noch kein Sponsor zugeordnet</option>
                )}
              </select>
            </div>

            <div className="acq-field">
              <label htmlFor="activity-channel">Kontaktweg</label>
              <p id="activity-channel-help">
                Wie der Kontakt stattgefunden hat.
              </p>
              <select
                aria-describedby="activity-channel-help"
                id="activity-channel"
                name="channel"
                ref={channelRef}
              >
                <option value="phone">Telefon</option>
                <option value="email">E-Mail</option>
                <option value="in_person">Persönlich</option>
              </select>
            </div>

            <div className="acq-field">
              <label htmlFor="activity-outcome">Ergebnis</label>
              <p id="activity-outcome-help">
                Der aktuelle Stand nach diesem Kontakt.
              </p>
              <select
                aria-describedby="activity-outcome-help"
                id="activity-outcome"
                name="outcome"
              >
                <option value="reached">Erreicht</option>
                <option value="no_answer">Nicht erreicht</option>
                <option value="interested">Interesse</option>
                <option value="follow_up">Später nachfassen</option>
                <option value="committed">Zusage</option>
                <option value="declined">Absage</option>
              </select>
            </div>

            <div className="acq-field acq-field--wide">
              <div className="acq-field__meta">
                <label htmlFor="activity-note">Kurze Notiz (optional)</label>
                <span id="activity-note-count">
                  {new Intl.NumberFormat("de-DE").format(note.length)} / 2.000
                </span>
              </div>
              <p id="activity-note-help">
                Sachlich und knapp; keine privaten oder besonders sensiblen
                Angaben notieren.
              </p>
              <textarea
                aria-describedby="activity-note-help activity-note-count"
                id="activity-note"
                maxLength={2000}
                name="note"
                onChange={(event) => setNote(event.target.value)}
                placeholder="Zum Beispiel: Angebot per E-Mail gewünscht."
                value={note}
              />
            </div>

            <fieldset className="acq-fieldset acq-field--wide">
              <legend>Nächster Schritt (optional)</legend>
              <p>
                Aktion und Datum gehören zusammen. Ohne beide Angaben wird keine
                Wiedervorlage angelegt.
              </p>
              <div className="acq-form acq-form--nested">
                <div className="acq-field">
                  <label htmlFor="activity-next-action">Nächste Aktion</label>
                  <input
                    id="activity-next-action"
                    maxLength={300}
                    name="nextAction"
                    onChange={(event) => setNextAction(event.target.value)}
                    placeholder="Angebot nachfassen"
                    required={Boolean(dueOn)}
                    value={nextAction}
                  />
                </div>
                <div className="acq-field">
                  <label htmlFor="activity-due-on">Fällig am</label>
                  <input
                    id="activity-due-on"
                    min={todayInBerlin()}
                    name="dueOn"
                    onChange={(event) => setDueOn(event.target.value)}
                    required={Boolean(nextAction.trim())}
                    type="date"
                    value={dueOn}
                  />
                </div>
              </div>
            </fieldset>

            <div className="acq-form__actions acq-field--wide">
              <Button
                data-testid="activity-submit"
                disabled={
                  !selected || !reminderPairComplete || record.isPending
                }
                type="submit"
              >
                {record.isPending
                  ? "Aktivität wird gespeichert …"
                  : "Aktivität speichern"}
              </Button>
            </div>
            <div
              aria-live="polite"
              className="acq-field--wide"
              id="activity-status"
              role="status"
            >
              {success ? (
                <StatusMessage tone="success">{success}</StatusMessage>
              ) : null}
              {record.isError ? (
                <StatusMessage tone="error">
                  {errorCopy(record.error)}
                </StatusMessage>
              ) : null}
            </div>
          </form>
        </section>

        <section aria-labelledby="reminder-heading" className="acq-board">
          <div className="acq-section-heading">
            <span aria-hidden="true" className="acq-section-heading__icon">
              <HugeiconsIcon
                icon={Calendar02Icon}
                size={20}
                strokeWidth={1.8}
              />
            </span>
            <div>
              <h2 id="reminder-heading">Heute im Blick</h2>
              <p>Überfälliges und heute Fälliges steht immer zuerst.</p>
            </div>
          </div>
          {board.isPending ? (
            <div aria-live="polite" className="acq-skeleton" role="status">
              <span />
              <span />
              <span />
              <p className="sr-only">Wiedervorlagen werden geladen</p>
            </div>
          ) : board.isError ? (
            <StatusMessage tone="error">
              <div>
                <strong>Wiedervorlagen nicht erreichbar</strong>
                <p>Prüfe deine Verbindung und lade die Arbeitsliste erneut.</p>
                <Button
                  onClick={() => void board.refetch()}
                  variant="secondary"
                >
                  Arbeitsliste neu laden
                </Button>
              </div>
            </StatusMessage>
          ) : board.data ? (
            <ActivityBoard board={board.data} onSelect={selectReminder} />
          ) : null}
        </section>
      </div>
    </div>
  );
}
