/*
 * "Warteschlange" sheet of the acquisition PWA (specs/pwa-offline-queue
 * §12.2–§12.6): every capture kept on the device with its state in text
 * and shape, the reason when Core refused it, and what the acquirer can do.
 */
import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type {
  CommitmentCaptureContextResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";

import {
  Button,
  ConfirmDialog,
  Icon,
  StatusIcon,
  StatusMessage,
} from "@leonaid/ui";

import { formatDateTime } from "../shared/dates";
import { conflictText } from "./conflicts";
import type { DeviceStore } from "./device-store";
import { EntryChoices } from "./entry-choices";
import { entryStateLabel, entryTitle, queueStateShape } from "./labels";
import type { QueueEntry } from "./queue";
import { useOfflineRuntime, useQueueSnapshot } from "./runtime";

const IOS_HINT_KEY = "leonaid-pwa-ios-hint-shown";

/** The device copies of the order context, for the window choices. */
function useCaptureContexts(
  store: DeviceStore | null,
  open: boolean,
  actionIds: readonly string[],
): ReadonlyMap<string, CommitmentCaptureContextResponse> {
  const [contexts, setContexts] = useState<
    ReadonlyMap<string, CommitmentCaptureContextResponse>
  >(new Map());
  const key = [...new Set(actionIds)].sort().join(",");
  useEffect(() => {
    if (!open || !store || !key) return;
    let cancelled = false;
    void Promise.all(
      key.split(",").map(async (actionId) => {
        const cached = await store
          .getCache<CommitmentCaptureContextResponse>("capture", actionId)
          .catch(() => undefined);
        return [actionId, cached?.value] as const;
      }),
    ).then((pairs) => {
      if (cancelled) return;
      setContexts(
        new Map(
          pairs.flatMap(([actionId, value]) =>
            value ? [[actionId, value] as const] : [],
          ),
        ),
      );
    });
    return () => {
      cancelled = true;
    };
  }, [key, open, store]);
  return contexts;
}

/** D1: the contact itself already reached Core (§11.4). */
function isStoredAtCore(entry: QueueEntry) {
  const code = entry.lastError?.code;
  return code === "follow_up_not_applied" || code === "status_not_applied";
}

function isStandaloneIos(): boolean {
  const standalone = (navigator as Navigator & { standalone?: boolean })
    .standalone;
  return standalone === true;
}

/** Shown once per device on an iPhone home-screen app (§12.6). */
function useIosHint(open: boolean): boolean {
  const [show, setShow] = useState(false);
  useEffect(() => {
    if (!open || !isStandaloneIos()) return;
    try {
      if (window.localStorage.getItem(IOS_HINT_KEY)) return;
      window.localStorage.setItem(IOS_HINT_KEY, "1");
    } catch {
      return;
    }
    setShow(true);
  }, [open]);
  return show;
}

export function QueueSheet({
  actionNames,
  client,
  loginHref,
  onClose,
  online,
  open,
}: {
  /** Action id → name, for the copy of §10.2. */
  readonly actionNames: ReadonlyMap<string, string>;
  readonly client: LeonAidApiClient;
  readonly loginHref: string;
  readonly onClose: () => void;
  readonly online: boolean;
  readonly open: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const { queue, store } = useOfflineRuntime();
  const snapshot = useQueueSnapshot();
  const contexts = useCaptureContexts(
    store,
    open,
    snapshot.entries.map((entry) => entry.actionId),
  );
  const iosHint = useIosHint(open);
  const waitingFor = (draftId: string) =>
    snapshot.entries.filter((entry) => entry.dependsOn === draftId).length;
  const [discarding, setDiscarding] = useState<QueueEntry | null>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  // Drafts and what waits for them do not wait for the network (§10.4).
  const waiting = snapshot.entries.filter(
    (entry) =>
      (entry.state === "queued" || entry.state === "sending") &&
      entry.kind !== "sponsor-draft" &&
      !entry.dependsOn,
  ).length;

  return (
    <dialog
      aria-labelledby="queue-sheet-title"
      className="pwa-sheet"
      data-testid="queue-sheet"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
      onClose={(event) => {
        if (event.target === event.currentTarget && open) onClose();
      }}
      ref={ref}
    >
      {open ? (
        <div className="pwa-sheet-body">
          <header className="pwa-sheet-header">
            <h2 id="queue-sheet-title">Warteschlange</h2>
            <button
              aria-label="Schließen"
              className="pwa-sheet-close"
              onClick={onClose}
              title="Schließen"
              type="button"
            >
              <Icon icon={X} size={20} />
            </button>
          </header>
          {snapshot.paused ? (
            <StatusMessage tone="warning">
              <p>
                Melde dich wieder an, damit LeonAid deine Einträge senden kann.
                Sie bleiben bis dahin auf diesem Gerät.
              </p>
              <a href={loginHref}>Zur Anmeldung</a>
            </StatusMessage>
          ) : null}
          {iosHint ? (
            <StatusMessage tone="info" data-testid="queue-ios-hint">
              Auf dem iPhone sendet LeonAid nur, solange die App geöffnet ist.
              Öffne sie, wenn du wieder Empfang hast.
            </StatusMessage>
          ) : null}
          {snapshot.evictable ? (
            <p className="small muted" data-testid="queue-evictable">
              Gerät kann Einträge löschen, wenn der Speicher knapp wird.
            </p>
          ) : null}
          <p className="small muted" data-testid="queue-summary">
            {snapshot.entries.length === 0
              ? "Alles gesendet. Auf diesem Gerät wartet nichts."
              : waiting
                ? `${waiting} ${waiting === 1 ? "Eintrag wartet" : "Einträge warten"} auf Versand.`
                : "Nichts wartet auf Versand."}
          </p>
          {waiting ? (
            <Button
              className="pwa-wide"
              data-testid="queue-send-now"
              disabled={!online || snapshot.sending}
              loading={snapshot.sending}
              onClick={() => void queue?.sendNow()}
              size="lg"
              variant="primary"
            >
              {online ? "Jetzt senden" : "Sendet, sobald du online bist"}
            </Button>
          ) : null}
          <ul className="pwa-queue" data-testid="queue-entries">
            {snapshot.entries.map((entry) => (
              <li
                className="pwa-queue-entry"
                data-entry-id={entry.entryId}
                data-state={entry.state}
                data-testid="queue-entry"
                key={entry.entryId}
              >
                <span className="pwa-queue-title">{entryTitle(entry)}</span>
                <span className="pwa-queue-meta small muted">
                  Erfasst am {formatDateTime(entry.capturedAt)}
                </span>
                <span className="pwa-queue-state" data-testid="queue-state">
                  <StatusIcon
                    label=""
                    size={16}
                    status={queueStateShape[entry.state]}
                  />
                  {entryStateLabel(entry)}
                </span>
                {entry.kind === "sponsor-draft" ? (
                  <p className="small" data-testid="queue-reason">
                    {`Neuer Sponsor ${entry.party.displayName} wartet auf deine Prüfung.`}
                    {waitingFor(entry.entryId)
                      ? ` ${waitingFor(entry.entryId)} ${waitingFor(entry.entryId) === 1 ? "Eintrag wartet" : "Einträge warten"} darauf.`
                      : ""}
                  </p>
                ) : entry.state === "conflict" ||
                  entry.state === "failed" ||
                  entry.state === "blocked" ||
                  entry.state === "expired" ? (
                  <p className="small" data-testid="queue-reason">
                    {conflictText(entry, actionNames.get(entry.actionId) ?? "")}
                  </p>
                ) : null}
                {queue ? (
                  <EntryChoices
                    client={client}
                    context={contexts.get(entry.actionId) ?? null}
                    entry={entry}
                    onDiscard={() => setDiscarding(entry)}
                    online={online}
                    queue={queue}
                  />
                ) : null}
              </li>
            ))}
            {snapshot.sent.map((entry) => (
              <li
                className="pwa-queue-entry"
                data-state="sent"
                data-testid="queue-entry"
                key={`sent-${entry.entryId}`}
              >
                <span className="pwa-queue-title">{entryTitle(entry)}</span>
                <span className="pwa-queue-state" data-testid="queue-state">
                  <StatusIcon label="" size={16} status="done" />
                  Gesendet
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <ConfirmDialog
        confirmLabel="Verwerfen"
        description={
          discarding
            ? [
                isStoredAtCore(discarding)
                  ? `${entryTitle(discarding)} ist bei LeonAid gespeichert. Verwerfen löscht nur den Hinweis auf diesem Gerät; der Rest wird nicht übernommen.`
                  : `${entryTitle(discarding)} wird von diesem Gerät gelöscht und nicht gesendet.`,
                ...snapshot.entries
                  .filter((entry) => entry.dependsOn === discarding.entryId)
                  .map((entry) => `Mit gelöscht: ${entryTitle(entry)}.`),
              ].join(" ")
            : ""
        }
        onConfirm={() => {
          const entry = discarding;
          setDiscarding(null);
          if (entry) void queue?.discard(entry.entryId);
        }}
        onOpenChange={(next) => {
          if (!next) setDiscarding(null);
        }}
        open={discarding !== null}
        title="Eintrag verwerfen?"
        tone="danger"
      />
    </dialog>
  );
}
