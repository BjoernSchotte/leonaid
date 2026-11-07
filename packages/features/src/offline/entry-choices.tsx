/*
 * The choices of one queue entry in the "Warteschlange" sheet
 * (specs/pwa-offline-queue §10): buttons for the simple ones, a window
 * picker and a delivery form where the acquirer has to add something.
 */
import { useState, type FormEvent } from "react";

import {
  ApiError,
  type CommitmentCaptureContextResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Button,
  buttonClassName,
  Field,
  Input,
  StatusMessage,
} from "@leonaid/ui";

import { PWA_BASE } from "@leonaid/ui/base-paths";
import { configuredWindowLabel } from "../commitments/order-format";
import {
  ResolutionError,
  applySimpleResolution,
  keepMyFollowUp,
} from "./apply-resolution";
import type { QueueController } from "./controller";
import type { QueueEntry } from "./queue";
import {
  choosableWindows,
  resolutionLabel,
  resolutionsFor,
  withDelivery,
  withWindow,
  type Resolution,
} from "./resolutions";

function errorText(error: unknown) {
  if (error instanceof ResolutionError) return error.message;
  if (
    error instanceof ApiError &&
    error.detail.code === "assignment_revision_conflict"
  ) {
    return "Der Sponsor wurde inzwischen wieder geändert. Öffne ihn, prüfe den Stand und erfasse die Wiedervorlage dort.";
  }
  if (error instanceof ApiError) return error.detail.message;
  return "Das hat gerade nicht geklappt. Prüfe deine Verbindung und versuche es erneut.";
}

export function EntryChoices({
  client,
  context,
  entry,
  onDiscard,
  online,
  queue,
}: {
  readonly client: LeonAidApiClient;
  /** The device copy of the order context (offers, windows). */
  readonly context: CommitmentCaptureContextResponse | null;
  readonly entry: QueueEntry;
  /** "Verwerfen" asks first (the sheet's confirmation). */
  readonly onDiscard: () => void;
  readonly online: boolean;
  readonly queue: QueueController;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [picking, setPicking] = useState<"window" | "delivery" | null>(null);
  const [copied, setCopied] = useState(false);

  if (entry.kind === "sponsor-draft") {
    return (
      <div className="pwa-queue-actions">
        <a
          aria-disabled={!online}
          className={buttonClassName({ size: "sm", variant: "secondary" })}
          data-testid="queue-check-draft"
          href={
            online
              ? `${PWA_BASE}sponsors?view=new&action=${encodeURIComponent(entry.actionId)}&draft=${encodeURIComponent(entry.entryId)}`
              : undefined
          }
        >
          Jetzt prüfen
        </a>
        <Button
          data-testid="queue-discard"
          onClick={onDiscard}
          size="sm"
          variant="ghost"
        >
          Verwerfen
        </Button>
      </div>
    );
  }

  async function choose(resolution: Resolution) {
    setError(null);
    if (resolution === "discard") {
      onDiscard();
      return;
    }
    if (resolution === "copy-note") {
      const note = entry.kind === "activity" ? (entry.request.note ?? "") : "";
      try {
        await navigator.clipboard.writeText(note);
        setCopied(true);
      } catch {
        setError("Die Notiz konnte nicht kopiert werden.");
      }
      return;
    }
    if (resolution === "other-window") {
      setPicking("window");
      return;
    }
    if (resolution === "complete-delivery") {
      setPicking("delivery");
      return;
    }
    setBusy(true);
    try {
      if (resolution === "keep-follow-up") {
        await keepMyFollowUp(client, queue, entry);
      } else if (!(await applySimpleResolution(queue, entry, resolution))) {
        setError("Diese Wahl ist für den Eintrag nicht möglich.");
      }
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setBusy(false);
    }
  }

  const windows = choosableWindows(context);
  const choices = resolutionsFor(entry);

  return (
    <>
      <div className="pwa-queue-actions">
        {entry.state === "failed" &&
        entry.lastError?.code !== "idempotency_conflict" ? (
          <Button
            disabled={!online}
            onClick={() => void queue.retry(entry.entryId)}
            size="sm"
            variant="secondary"
          >
            Erneut versuchen
          </Button>
        ) : null}
        {entry.state === "sending" || entry.state === "queued"
          ? null
          : choices.map((resolution) => (
              <Button
                data-resolution={resolution}
                data-testid={
                  resolution === "discard" ? "queue-discard" : "queue-choice"
                }
                disabled={
                  busy ||
                  (resolution === "keep-follow-up" && !online) ||
                  ((resolution === "other-window" ||
                    resolution === "complete-delivery") &&
                    windows.length === 0)
                }
                key={resolution}
                loading={busy && resolution === "keep-follow-up"}
                onClick={() => void choose(resolution)}
                size="sm"
                variant={
                  resolution === "discard" || resolution === "discard-follow-up"
                    ? "ghost"
                    : "secondary"
                }
              >
                {resolution === "copy-note" && copied
                  ? "Notiz kopiert"
                  : resolutionLabel[resolution]}
              </Button>
            ))}
        {entry.state === "queued" ? (
          <Button
            data-testid="queue-discard"
            onClick={onDiscard}
            size="sm"
            variant="ghost"
          >
            Verwerfen
          </Button>
        ) : null}
      </div>
      {error ? <StatusMessage tone="error">{error}</StatusMessage> : null}
      {picking && entry.kind === "commitment" ? (
        <WindowForm
          delivery={picking === "delivery"}
          onCancel={() => setPicking(null)}
          onSave={async (windowId, recipient) => {
            const window = windows.find((item) => item.id === windowId);
            if (!window) return;
            await queue.replace(
              entry.entryId,
              () =>
                recipient
                  ? withDelivery(
                      entry,
                      {
                        deliveryRecipient: recipient,
                        deliveryWindowId: window.id,
                      },
                      window,
                    )
                  : withWindow(entry, window),
              { newKey: true },
            );
            setPicking(null);
          }}
          windows={windows}
        />
      ) : null}
    </>
  );
}

function WindowForm({
  delivery,
  onCancel,
  onSave,
  windows,
}: {
  readonly delivery: boolean;
  readonly onCancel: () => void;
  readonly onSave: (
    windowId: string,
    recipient: {
      readonly recipientName: string;
      readonly streetLine1: string;
      readonly postalCode: string;
      readonly city: string;
      readonly countryCode: string;
    } | null,
  ) => Promise<void>;
  readonly windows: ReturnType<typeof choosableWindows>;
}) {
  const [windowId, setWindowId] = useState(windows[0]?.id ?? "");
  const [missing, setMissing] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const text = (name: string) => String(values.get(name) ?? "").trim();
    const recipient = delivery
      ? {
          city: text("city"),
          countryCode: "DE",
          postalCode: text("postalCode"),
          recipientName: text("recipientName"),
          streetLine1: text("streetLine1"),
        }
      : null;
    if (
      !windowId ||
      (recipient &&
        ![
          recipient.recipientName,
          recipient.streetLine1,
          recipient.postalCode,
          recipient.city,
        ].every(Boolean))
    ) {
      setMissing(true);
      return;
    }
    await onSave(windowId, recipient);
  }

  return (
    <form className="stack" data-testid="queue-window-form" onSubmit={submit}>
      <fieldset className="pwa-fieldset">
        <legend className="field-label">Lieferfenster</legend>
        <div className="pwa-options">
          {windows.map((window) => (
            <label
              className={`pwa-option${windowId === window.id ? " is-checked" : ""}`}
              key={window.id}
            >
              <input
                checked={windowId === window.id}
                name="queue-window"
                onChange={() => setWindowId(window.id)}
                type="radio"
                value={window.id}
              />
              {configuredWindowLabel(window)}
              {window.fullyBooked ? " (ausgebucht)" : ""}
            </label>
          ))}
        </div>
      </fieldset>
      {delivery ? (
        <>
          <Field label="Empfänger">
            <Input maxLength={200} name="recipientName" />
          </Field>
          <Field label="Straße und Hausnummer">
            <Input
              autoComplete="address-line1"
              maxLength={200}
              name="streetLine1"
            />
          </Field>
          <div className="pwa-two">
            <Field label="PLZ">
              <Input
                autoComplete="postal-code"
                maxLength={20}
                name="postalCode"
              />
            </Field>
            <Field label="Ort">
              <Input
                autoComplete="address-level2"
                maxLength={120}
                name="city"
              />
            </Field>
          </div>
        </>
      ) : null}
      {missing ? (
        <StatusMessage tone="error">
          {delivery
            ? "Bitte Lieferfenster und die ganze Lieferadresse angeben."
            : "Bitte ein Lieferfenster wählen."}
        </StatusMessage>
      ) : null}
      <div className="pwa-queue-actions">
        <Button size="sm" type="submit" variant="primary">
          Übernehmen und senden
        </Button>
        <Button onClick={onCancel} size="sm" variant="ghost">
          Abbrechen
        </Button>
      </div>
    </form>
  );
}
