/*
 * "Kontakt mit …" bottom sheet of the sponsor detail (prototype
 * pwa/Acquire.tsx ContactSheet): outcome, way of contact, follow-up, note.
 */
import { X } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type RefObject,
} from "react";

import {
  ApiError,
  type AcquisitionActivityWorkItemResponse,
  type LeonAidApiClient,
  type RecordAcquisitionActivityRequest,
} from "@leonaid/api-client";
import {
  Button,
  Field,
  Icon,
  Input,
  StatusIcon,
  StatusMessage,
  Textarea,
  useOptionalToast,
  type StatusShape,
} from "@leonaid/ui";

import { localIsoDate } from "../shared/dates";

type Outcome = RecordAcquisitionActivityRequest["outcome"];
type Channel = RecordAcquisitionActivityRequest["channel"];

export const outcomeLabels: Readonly<Record<Outcome, string>> = {
  reached: "Erreicht",
  no_answer: "Nicht erreicht",
  interested: "Interessiert",
  follow_up: "Später nachfassen",
  committed: "Zugesagt",
  declined: "Abgesagt",
};

const outcomeShapes: Readonly<Record<Outcome, StatusShape>> = {
  reached: "open",
  no_answer: "draft",
  interested: "review",
  follow_up: "progress",
  committed: "done",
  declined: "cancelled",
};

export const channelLabels: Readonly<Record<Channel, string>> = {
  phone: "Telefon",
  email: "E-Mail",
  in_person: "Persönlich",
};

const OUTCOMES: readonly Outcome[] = [
  "no_answer",
  "reached",
  "interested",
  "follow_up",
  "committed",
  "declined",
];

/** A follow-up is planned unless the sponsor decided (prototype rule). */
function plansFollowUp(outcome: Outcome) {
  return outcome !== "committed" && outcome !== "declined";
}

/** The prototype proposes a follow-up three days later. */
function inThreeDays(now: Date = new Date()) {
  return localIsoDate(new Date(now.getTime() + 3 * 86_400_000));
}

function errorCopy(error: unknown) {
  if (
    error instanceof ApiError &&
    error.detail.code === "assignment_revision_conflict"
  ) {
    return "Der Sponsor wurde parallel geändert. Der aktuelle Stand ist geladen; prüfe deine Angaben und speichere erneut.";
  }
  if (error instanceof ApiError && error.detail.code === "contact_suppressed") {
    return "Dieser Kontaktweg ist für den Sponsor gesperrt. Wähle einen erlaubten Kontaktweg.";
  }
  if (error instanceof ApiError && error.status === 403) {
    return "Du bist dieser Aktion nicht als Akquisiteur zugeordnet.";
  }
  return "Der Kontakt konnte nicht gespeichert werden. Prüfe deine Verbindung; deine Eingaben bleiben erhalten.";
}

export function ContactSheet({
  actionId,
  client,
  item,
  onClose,
  open,
  returnFocus,
}: {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  readonly item: AcquisitionActivityWorkItemResponse;
  readonly onClose: () => void;
  readonly open: boolean;
  /** Takes the focus when the sheet closes ("Kontakt erfassen"). */
  readonly returnFocus?: RefObject<HTMLElement | null>;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const queries = useQueryClient();
  const toast = useOptionalToast();
  const allowed = (channel: Channel) =>
    channel === "in_person" ||
    !item.suppressedChannels.includes(channel as "email" | "phone");
  const [outcome, setOutcome] = useState<Outcome>("no_answer");
  const [channel, setChannel] = useState<Channel>(
    allowed("phone") ? "phone" : "in_person",
  );
  const [dueOn, setDueOn] = useState(inThreeDays);
  const [nextAction, setNextAction] = useState("Nachfassen");
  const [note, setNote] = useState("");

  const opener = useRef<Element | null>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      // A failed save of an earlier opening is not shown again.
      record.reset();
      opener.current = document.activeElement;
      dialog.showModal();
    }
    if (!open && dialog.open) {
      dialog.close();
      // The sheet returns the focus itself (no reliance on the browser's
      // or the shared Modal's fallback): to "Kontakt erfassen", else to
      // what had it before.
      const target =
        returnFocus?.current ??
        (opener.current instanceof HTMLElement ? opener.current : null);
      target?.focus();
    }
  }, [open]);

  const record = useMutation({
    mutationFn: (body: RecordAcquisitionActivityRequest) =>
      client.recordAcquisitionActivity(actionId, body),
    onError: () => {
      void queries.invalidateQueries({
        queryKey: ["acquisition-activity-board", actionId],
      });
    },
    onSuccess: async () => {
      toast?.show({ title: "Kontakt erfasst.", tone: "success" });
      setNote("");
      await queries.invalidateQueries({
        queryKey: ["acquisition-activity-board", actionId],
      });
      onClose();
    },
  });

  const followUp = plansFollowUp(outcome);
  const pairMissing =
    followUp &&
    ((dueOn.length > 0 && nextAction.trim().length === 0) ||
      (dueOn.length === 0 && nextAction.trim().length > 0));

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pairMissing || !allowed(channel)) return;
    record.mutate({
      channel,
      dueOn: followUp && dueOn ? dueOn : null,
      nextAction: followUp && dueOn ? nextAction.trim() : null,
      note: note.trim() || null,
      outcome,
      partyId: item.partyId,
      partyKind: item.partyKind,
      revision: item.revision,
    });
  }

  return (
    <dialog
      aria-labelledby="contact-sheet-title"
      className="pwa-sheet"
      data-testid="contact-sheet"
      onCancel={(event) => {
        event.preventDefault();
        if (!record.isPending) onClose();
      }}
      onClick={(event) => {
        if (event.target === ref.current && !record.isPending) onClose();
      }}
      ref={ref}
    >
      {open ? (
        <form className="pwa-sheet-body" id="activity-form" onSubmit={submit}>
          <header className="pwa-sheet-header">
            <h2 id="contact-sheet-title">
              Kontakt mit {item.partyDisplayName}
            </h2>
            <button
              aria-label="Schließen"
              className="pwa-sheet-close"
              disabled={record.isPending}
              onClick={onClose}
              type="button"
            >
              <Icon icon={X} size={20} />
            </button>
          </header>
          <fieldset className="pwa-fieldset">
            <legend className="field-label">Wie ist es gelaufen?</legend>
            <div className="pwa-options">
              {OUTCOMES.map((value) => (
                <label
                  className={`pwa-option${outcome === value ? " is-checked" : ""}`}
                  key={value}
                >
                  <input
                    checked={outcome === value}
                    className="sr-only"
                    name="outcome"
                    onChange={() => setOutcome(value)}
                    type="radio"
                    value={value}
                  />
                  {/* Decorative: the word follows. */}
                  <StatusIcon
                    label=""
                    size={16}
                    status={outcomeShapes[value]}
                  />
                  {outcomeLabels[value]}
                </label>
              ))}
            </div>
          </fieldset>
          <fieldset className="pwa-fieldset">
            <legend className="field-label">Kontaktweg</legend>
            <div aria-label="Kontaktweg" className="pwa-segment" role="group">
              {(["phone", "email", "in_person"] as const).map((value) => (
                <button
                  aria-pressed={channel === value}
                  disabled={!allowed(value)}
                  key={value}
                  onClick={() => setChannel(value)}
                  title={
                    allowed(value) ? undefined : "Für diesen Sponsor gesperrt"
                  }
                  type="button"
                >
                  {channelLabels[value]}
                </button>
              ))}
            </div>
            {item.suppressedChannels.some(
              (value) => value === "email" || value === "phone",
            ) ? (
              <p className="small muted">
                Gesperrte Kontaktwege sind nicht wählbar.
              </p>
            ) : null}
          </fieldset>
          {followUp ? (
            <>
              <Field label="Wiedervorlage am" optional>
                <Input
                  id="activity-due-on"
                  min={localIsoDate()}
                  onChange={(event) => setDueOn(event.target.value)}
                  type="date"
                  value={dueOn}
                />
              </Field>
              <Field
                error={
                  pairMissing
                    ? "Datum und nächster Schritt gehören zusammen."
                    : undefined
                }
                label="Nächster Schritt"
              >
                <Input
                  id="activity-next-action"
                  maxLength={300}
                  onChange={(event) => setNextAction(event.target.value)}
                  value={nextAction}
                />
              </Field>
            </>
          ) : null}
          <Field label="Notiz" optional>
            <Textarea
              id="activity-note"
              maxLength={2000}
              onChange={(event) => setNote(event.target.value)}
              placeholder="z. B. Chefin ab Montag wieder da"
              rows={3}
              value={note}
            />
          </Field>
          {record.isError ? (
            <StatusMessage tone="error">
              {errorCopy(record.error)}
            </StatusMessage>
          ) : null}
          <Button
            className="pwa-wide"
            data-testid="activity-submit"
            disabled={Boolean(pairMissing)}
            loading={record.isPending}
            size="lg"
            type="submit"
            variant="primary"
          >
            Speichern
          </Button>
        </form>
      ) : null}
    </dialog>
  );
}
