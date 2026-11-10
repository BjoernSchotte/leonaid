import { useMutation } from "@tanstack/react-query";
import { Ban } from "lucide-react";
import { useState } from "react";

import type {
  CommitmentRecordResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Button,
  Field,
  Modal,
  StatusMessage,
  Textarea,
  useOptionalToast,
} from "@leonaid/ui";

import { actionErrorMessage } from "../action-admin/errors";
import {
  needsFreshLogin,
  saveFreshLoginDraft,
  takeFreshLoginDraft,
} from "../action-admin/fresh-login-draft";
import { commandKey, forgetCommandKey } from "../invoices/invoice-model";

export const MIN_REASON = 8;
const MAX_REASON = 500;
const MAX_NOTE = 1000;

/**
 * Why the server would refuse to cancel this order, in the words of its
 * answer; null when it may be cancelled. The server decides; this only
 * explains a refusal before the person types a reason.
 */
export function cancellationBlock(
  record: CommitmentRecordResponse,
): string | null {
  if (record.commitment.status === "cancelled") return null;
  if (record.delivered) {
    return "Die Bestellung ist bereits geliefert und kann nicht mehr storniert werden.";
  }
  // Active (not reversed) payment entries, ADR-0014. A cancelled invoice is
  // closed: its payments stay and its refund is tracked with the invoice.
  if (
    record.invoice?.status !== "cancelled" &&
    (record.invoice?.paidMinor ?? 0) > 0
  ) {
    return `Zur Rechnung ${record.invoice!.number} ist eine Zahlung erfasst. Buchen Sie die Zahlung in der Rechnung erst zurück (Zahlung zurückbuchen), dann können Sie die Bestellung stornieren.`;
  }
  return null;
}

/** The invoice the cancellation cancels with the order (ADR-0009). */
export function invoiceToCancel(record: CommitmentRecordResponse) {
  const invoice = record.invoice;
  return invoice && (invoice.status === "issued" || invoice.status === "sent")
    ? invoice
    : null;
}

/**
 * True when the server sends the buyer a cancellation notice: orders from
 * the public form whose buyer address still exists (application/order_mails).
 */
export function notifiesBuyer(record: CommitmentRecordResponse): boolean {
  const { commitment } = record;
  return (
    commitment.source === "public_form" &&
    Boolean(commitment.buyer.email?.trim())
  );
}

const draftKey = (commitmentId: string) => `order-cancellation:${commitmentId}`;
const commandStorageKey = (commitmentId: string) =>
  `leonaid.order-cancellation.${commitmentId}`;

interface CancellationDraft {
  readonly reason: string;
  readonly note: string;
}

/**
 * The reason and note typed before the fresh sign-in, once, for this
 * account; the pane reopens the dialog with them.
 */
export function takeCancellationDraft(
  commitmentId: string,
  userId: string,
): CancellationDraft | null {
  const raw = takeFreshLoginDraft(draftKey(commitmentId), userId);
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<CancellationDraft>;
    return typeof value.reason === "string"
      ? {
          reason: value.reason,
          note: typeof value.note === "string" ? value.note : "",
        }
      : null;
  } catch {
    return null;
  }
}

interface OrderCancellationDialogProps {
  readonly client: LeonAidApiClient;
  readonly record: CommitmentRecordResponse;
  readonly userId: string;
  readonly initial?: CancellationDraft | null;
  readonly onClose: () => void;
  /** After a cancellation and after a refusal: the list reloads. */
  readonly onChanged: () => void;
}

/**
 * Explicit command: cancels an order that is not delivered yet. The order
 * stays with all its data; an open invoice is cancelled with it and keeps
 * its number and PDF. The buyer of a public order gets a cancellation
 * notice from the server; nobody else is e-mailed.
 */
export function OrderCancellationDialog({
  client,
  initial,
  onChanged,
  onClose,
  record,
  userId,
}: OrderCancellationDialogProps) {
  const { commitment } = record;
  const toast = useOptionalToast();
  const [reason, setReason] = useState(initial?.reason ?? "");
  const [note, setNote] = useState(initial?.note ?? "");
  const [submitted, setSubmitted] = useState(false);
  const [serverError, setServerError] = useState<string>();
  const storageKey = commandStorageKey(commitment.id);
  const block = cancellationBlock(record);
  const invoice = invoiceToCancel(record);

  const cancellation = useMutation({
    mutationFn: () =>
      client.cancelCommitment(
        commitment.actionId,
        commitment.id,
        {
          expectedVersion: commitment.deliveryCompletionVersion,
          reason: reason.trim(),
          note: note.trim() || null,
        },
        {
          headers: {
            "Idempotency-Key": commandKey(storageKey, "order-cancellation"),
          },
        },
      ),
    onError(cause) {
      if (needsFreshLogin(cause)) {
        // The page reloads after the sign-in; the pane reopens this dialog.
        saveFreshLoginDraft(
          draftKey(commitment.id),
          userId,
          JSON.stringify({ reason, note }),
        );
      }
      const message = actionErrorMessage(cause);
      setServerError(message.message);
      // A refusal means the list is behind (version, delivery, payment).
      if (message.conflict) onChanged();
    },
    onSuccess(result) {
      forgetCommandKey(storageKey);
      const invoiceNumber = result.cancellation.invoiceNumber;
      const cancellationNumber = result.cancellation.invoiceCancellationNumber;
      toast?.show({
        title: "Bestellung storniert.",
        description: invoiceNumber
          ? cancellationNumber
            ? `Rechnung ${invoiceNumber} ist ebenfalls storniert. Stornorechnung ${cancellationNumber} wurde ausgestellt.`
            : `Rechnung ${invoiceNumber} ist ebenfalls storniert.`
          : undefined,
        tone: "success",
      });
      onChanged();
      onClose();
    },
  });

  const trimmed = reason.trim().replace(/\s+/g, " ");
  const reasonError =
    submitted && trimmed.length < MIN_REASON
      ? `Bitte geben Sie einen Grund mit mindestens ${MIN_REASON} Zeichen an.`
      : undefined;

  function submit() {
    if (cancellation.isPending || block) return;
    setSubmitted(true);
    setServerError(undefined);
    if (trimmed.length < MIN_REASON) return;
    cancellation.mutate();
  }

  return (
    <Modal
      description="Die Bestellung bleibt mit allen Angaben erhalten und wird als storniert markiert. Sie verlässt sofort die Lieferplanung und zählt nicht mehr in Summen."
      footer={
        <>
          <Button
            disabled={cancellation.isPending}
            onClick={onClose}
            variant="ghost"
          >
            Abbrechen
          </Button>
          <Button
            data-testid="cancel-order"
            disabled={Boolean(block)}
            icon={Ban}
            loading={cancellation.isPending}
            onClick={submit}
            variant="danger"
          >
            Stornieren
          </Button>
        </>
      }
      onClose={() => {
        if (!cancellation.isPending) onClose();
      }}
      open
      role="alertdialog"
      title={`Bestellung von ${commitment.buyer.displayName} stornieren?`}
    >
      <form
        className="stack"
        data-testid="order-cancellation-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        {block ? (
          <StatusMessage tone="error">{block}</StatusMessage>
        ) : (
          <>
            {invoice ? (
              <StatusMessage tone="warning">
                <strong>Rechnung {invoice.number} wird mitstorniert.</strong>{" "}
                Sie bleibt mit Nummer, Daten und PDF unverändert erhalten und
                ist danach als storniert markiert. LeonAid stellt dazu eine
                Stornorechnung aus. Dafür bestätigen Sie Ihre Anmeldung
                gegebenenfalls erneut.
              </StatusMessage>
            ) : null}
            <Field
              error={reasonError}
              hint="Erscheint in der Historie der Bestellung."
              id={`order-cancel-reason-${commitment.id}`}
              label="Grund der Stornierung"
              required
            >
              <Textarea
                autoFocus
                data-testid="order-cancellation-reason"
                maxLength={MAX_REASON}
                onChange={(event) => setReason(event.target.value)}
                placeholder="z. B. Sponsor hat die Bestellung zurückgezogen"
                value={reason}
              />
            </Field>
            <Field
              hint="Nur intern sichtbar."
              id={`order-cancel-note-${commitment.id}`}
              label="Notiz"
              optional
            >
              <Textarea
                data-testid="order-cancellation-note"
                maxLength={MAX_NOTE}
                onChange={(event) => setNote(event.target.value)}
                value={note}
              />
            </Field>
            <StatusMessage tone="info">
              {notifiesBuyer(record)
                ? "Der Besteller erhält eine E-Mail über die Stornierung, ohne Grund und Notiz."
                : "LeonAid benachrichtigt den Besteller nicht automatisch. Bitte informieren Sie ihn selbst über die Stornierung."}
            </StatusMessage>
          </>
        )}
        {serverError ? (
          <StatusMessage tone="error">{serverError}</StatusMessage>
        ) : null}
        <button hidden type="submit" />
      </form>
    </Modal>
  );
}
