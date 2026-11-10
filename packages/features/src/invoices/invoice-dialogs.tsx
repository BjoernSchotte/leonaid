import { useMutation } from "@tanstack/react-query";
import { Ban } from "lucide-react";
import { useState } from "react";

import type {
  InvoiceRecordResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Button,
  Field,
  Input,
  Modal,
  StatusMessage,
  Textarea,
  useOptionalToast,
} from "@leonaid/ui";

import { actionErrorMessage } from "../action-admin/errors";
import {
  formatMoney,
  isoDay,
  localIsoDate,
  parseAmountMinor,
} from "./invoice-format";
import {
  commandKey,
  forgetCommandKey,
  refundCommandStorageKey,
  refundWithdrawalCommandStorageKey,
  invoiceSettlement,
  paymentCommandStorageKey,
  settlementCommandStorageKey,
} from "./invoice-model";

interface SettlementDialogProps {
  readonly client: LeonAidApiClient;
  /** The invoice the dialog is for; null keeps it closed. */
  readonly record: InvoiceRecordResponse | null;
  readonly onClose: () => void;
  readonly onChanged: () => void;
}

/**
 * Explicit command: records one received payment entry. The amount starts
 * as the open remainder, so a full payment stays one click; a partial or an
 * over payment is typed over it.
 */
export function PaymentDialog(props: SettlementDialogProps) {
  // A fresh form per invoice: the key resets every field.
  return props.record ? (
    <PaymentForm
      key={props.record.invoice.id}
      {...props}
      record={props.record}
    />
  ) : null;
}

function PaymentForm({
  client,
  onChanged,
  onClose,
  record,
}: SettlementDialogProps & { readonly record: InvoiceRecordResponse }) {
  const { invoice } = record;
  // The version the form was opened with: if another person books in the
  // meantime, the server refuses this entry instead of double counting.
  const [openedVersion] = useState(() => invoiceSettlement(record).version);
  const toast = useOptionalToast();
  const [amount, setAmount] = useState(() =>
    record.openMinor > 0 ? amountInput(record.openMinor) : "",
  );
  const [receivedOn, setReceivedOn] = useState(localIsoDate);
  const [reference, setReference] = useState("");
  const [note, setNote] = useState("");
  const [amountError, setAmountError] = useState<string>();
  const [dateError, setDateError] = useState<string>();
  const [serverError, setServerError] = useState<string>();
  // One key per form and version: a retry of this form replays, a later
  // installment after any change gets its own key.
  const storageKey = paymentCommandStorageKey(invoice.id, openedVersion);
  const open = formatMoney(record.openMinor, invoice.currency);
  const minDate = isoDay(invoice.issuedAt);
  const today = localIsoDate();

  const payment = useMutation({
    mutationFn: (amountMinor: number) =>
      client.recordInvoicePayment(
        invoice.actionId,
        invoice.id,
        {
          amountMinor,
          currency: invoice.currency,
          receivedOn,
          reference: reference.trim() || invoice.paymentReference,
          note: note.trim() || null,
          expectedSettlementVersion: openedVersion,
        },
        {
          headers: {
            "Idempotency-Key": commandKey(storageKey, "poc095:payment"),
          },
        },
      ),
    onError(cause) {
      setServerError(actionErrorMessage(cause).message);
    },
    onSuccess(result) {
      forgetCommandKey(storageKey);
      toast?.show(
        result.replayed
          ? {
              title: `Diese Zahlung war bereits erfasst.`,
              description: `Für ${invoice.number} wurde kein zweiter Eintrag angelegt.`,
              tone: "info",
            }
          : {
              title: `Zahlung für ${invoice.number} erfasst.`,
              tone: "success",
            },
      );
      onChanged();
      onClose();
    },
  });

  function submit() {
    if (payment.isPending) return;
    setServerError(undefined);
    const minor = parseAmountMinor(amount);
    if (minor === null) {
      setAmountError(
        `Bitte einen Betrag wie ${open.replace(/\s?€/, "")} eingeben.`,
      );
      return;
    }
    if (minor <= 0) {
      setAmountError("Der eingegangene Betrag muss größer als 0,00 € sein.");
      return;
    }
    if (!receivedOn || receivedOn < minDate || receivedOn > today) {
      setDateError("Das Eingangsdatum liegt zwischen Ausstellung und heute.");
      return;
    }
    payment.mutate(minor);
  }

  return (
    <Modal
      className="inv-dialog"
      description={`Offener Betrag: ${open} von ${record.buyerDisplayName}`}
      footer={
        <>
          <Button
            disabled={payment.isPending}
            onClick={onClose}
            variant="ghost"
          >
            Abbrechen
          </Button>
          <Button
            data-testid="record-payment"
            loading={payment.isPending}
            onClick={submit}
            variant="primary"
          >
            Zahlung erfassen
          </Button>
        </>
      }
      onClose={() => {
        if (!payment.isPending) onClose();
      }}
      open
      title={`Zahlung für ${invoice.number} erfassen`}
    >
      <form
        className="stack"
        data-testid="payment-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Field
          error={amountError}
          hint={amountHint(
            parseAmountMinor(amount),
            record.openMinor,
            invoice.currency,
          )}
          id={`pay-amount-${invoice.id}`}
          label="Eingegangener Betrag in €"
        >
          <Input
            autoComplete="off"
            autoFocus
            data-testid="payment-amount"
            inputMode="decimal"
            onChange={(event) => {
              setAmount(event.target.value);
              setAmountError(undefined);
            }}
            placeholder={open.replace(/\s?€/, "")}
            value={amount}
          />
        </Field>
        <Field
          error={dateError}
          id={`pay-date-${invoice.id}`}
          label="Eingangsdatum"
        >
          <Input
            data-testid="payment-date"
            max={today}
            min={minDate}
            onChange={(event) => {
              setReceivedOn(event.target.value);
              setDateError(undefined);
            }}
            type="date"
            value={receivedOn}
          />
        </Field>
        <Field
          hint={`Leer gelassen gilt die Zahlungsreferenz der Rechnung (${invoice.paymentReference}).`}
          id={`pay-ref-${invoice.id}`}
          label="Verwendungszweck"
          optional
        >
          <Input
            data-testid="payment-reference"
            maxLength={160}
            onChange={(event) => setReference(event.target.value)}
            placeholder={invoice.paymentReference}
            value={reference}
          />
        </Field>
        <Field id={`pay-note-${invoice.id}`} label="Notiz" optional>
          <Input
            data-testid="payment-note"
            maxLength={500}
            onChange={(event) => setNote(event.target.value)}
            placeholder="z. B. Rest kommt im Dezember"
            value={note}
          />
        </Field>
        {serverError ? (
          <StatusMessage tone="error">{serverError}</StatusMessage>
        ) : null}
        <button hidden type="submit" />
      </form>
    </Modal>
  );
}

/** "360,00": an amount in the German format the field accepts. */
function amountInput(minor: number) {
  return new Intl.NumberFormat("de-DE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(minor / 100);
}

/** What the typed amount does to the remainder, before it is booked. */
function amountHint(minor: number | null, openMinor: number, currency: string) {
  if (minor === null || minor <= 0) {
    return "Teil- und Überzahlungen sind möglich.";
  }
  if (minor < openMinor) {
    return `Teilzahlung: Danach bleiben ${formatMoney(openMinor - minor, currency)} offen.`;
  }
  if (minor > openMinor) {
    return `Überzahlung um ${formatMoney(minor - openMinor, currency)}. Die Differenz erstatten Sie außerhalb von LeonAid.`;
  }
  return "Vollständige Zahlung des offenen Betrags.";
}

const MIN_REASON = 8;

interface CancellationDialogProps extends SettlementDialogProps {
  /** Server right `mayIssue`: may send the cancellation invoice by e-mail. */
  readonly canManageDelivery: boolean;
}

/**
 * Explicit command: cancels an issued invoice for good. The record and its
 * PDF stay, and the server issues the cancellation invoice in the same step;
 * a correction is a new, separately numbered invoice.
 */
export function CancellationDialog(props: CancellationDialogProps) {
  return props.record ? (
    <CancellationForm
      key={props.record.invoice.id}
      {...props}
      record={props.record}
    />
  ) : null;
}

function CancellationForm({
  canManageDelivery,
  client,
  onChanged,
  onClose,
  record,
}: CancellationDialogProps & { readonly record: InvoiceRecordResponse }) {
  const { invoice } = record;
  const toast = useOptionalToast();
  const [reason, setReason] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [serverError, setServerError] = useState<string>();
  const storageKey = settlementCommandStorageKey(invoice.id, "cancellation");
  const receivedMinor = invoiceSettlement(record).paidMinor;
  // The cancellation invoice goes where the invoice went: offered only when
  // the invoice itself reached the recipient by e-mail and this person may
  // send. Without a stored address the server would refuse the whole step.
  const recipientEmail = invoice.recipient.email;
  const offerSend =
    canManageDelivery &&
    Boolean(recipientEmail) &&
    record.deliveries.some((delivery) => delivery.status === "sent");
  const [send, setSend] = useState(true);
  const sendCancellation = offerSend && send;

  const cancellation = useMutation({
    mutationFn: () =>
      client.cancelInvoice(
        invoice.actionId,
        invoice.id,
        offerSend
          ? { reason: reason.trim(), sendCancellation }
          : { reason: reason.trim() },
        {
          headers: {
            "Idempotency-Key": commandKey(storageKey, "poc095:cancellation"),
          },
        },
      ),
    onError(cause) {
      setServerError(actionErrorMessage(cause).message);
    },
    onSuccess(result) {
      forgetCommandKey(storageKey);
      toast?.show({
        title: result.number
          ? `${invoice.number} storniert. Stornorechnung ${result.number} ausgestellt.`
          : `${invoice.number} storniert.`,
        description: sendCancellation
          ? `Die Stornorechnung geht per E-Mail an ${recipientEmail}.`
          : undefined,
        tone: "success",
      });
      onChanged();
      onClose();
    },
  });

  const tooShort = reason.trim().length < MIN_REASON;
  const error =
    submitted && tooShort
      ? `Bitte einen Grund mit mindestens ${MIN_REASON} Zeichen angeben.`
      : undefined;

  function submit() {
    if (cancellation.isPending) return;
    setSubmitted(true);
    setServerError(undefined);
    if (tooShort) return;
    cancellation.mutate();
  }

  return (
    <Modal
      className="inv-dialog"
      description="Die Rechnung bleibt mit Nummer, Daten und PDF erhalten und wird als storniert markiert. LeonAid stellt dazu eine Stornorechnung aus: Sie erhält eine eigene Nummer aus dem Nummernkreis der Rechnungen und nennt diese Rechnung. Für eine Korrektur erfassen Sie danach eine neue Bestellung und stellen deren Rechnung aus."
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
            data-testid="cancel-invoice"
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
      title={`${invoice.number} stornieren?`}
    >
      <form
        className="stack"
        data-testid="cancellation-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Field
          error={error}
          hint="Erscheint in der Historie der Rechnung."
          id={`cancel-reason-${invoice.id}`}
          label="Grund der Stornierung"
        >
          <Textarea
            autoFocus
            data-testid="cancellation-reason"
            maxLength={500}
            onChange={(event) => setReason(event.target.value)}
            placeholder="z. B. Sponsor hat doppelt bestellt"
            value={reason}
          />
        </Field>
        {receivedMinor > 0 ? (
          <StatusMessage tone="warning">
            <span data-testid="cancellation-received">
              Auf diese Rechnung sind{" "}
              {formatMoney(receivedMinor, invoice.currency)} eingegangen. Die
              Zahlung bleibt erfasst, und die Stornorechnung nennt den
              erhaltenen Betrag. Die Erstattung überweisen Sie außerhalb von
              LeonAid und vermerken sie danach mit „Erstattung erledigt“.
            </span>
          </StatusMessage>
        ) : null}
        {offerSend ? (
          <div className="field">
            <label className="checkbox">
              <input
                checked={send}
                data-testid="send-cancellation-with-cancel"
                disabled={cancellation.isPending}
                onChange={(event) => {
                  // Another body is another command: it gets its own key.
                  forgetCommandKey(storageKey);
                  setSend(event.target.checked);
                }}
                type="checkbox"
              />
              Stornorechnung gleich senden
            </label>
            <p className="field-hint">
              Die Stornorechnung geht als PDF per E-Mail an {recipientEmail},
              sobald sie erzeugt ist.
            </p>
          </div>
        ) : null}
        {serverError ? (
          <StatusMessage tone="error">{serverError}</StatusMessage>
        ) : null}
      </form>
    </Modal>
  );
}

const refundErrors: Readonly<Record<string, string>> = {
  invoice_refund_already_settled:
    "Die Erstattung ist bereits als erledigt vermerkt.",
  invoice_refund_not_due:
    "Für diese Rechnung ist kein Zahlungseingang erfasst. Es gibt nichts zu erstatten.",
  invoice_refund_future_date:
    "Das Datum der Erstattung darf nicht in der Zukunft liegen.",
  invoice_refund_before_invoice:
    "Das Datum der Erstattung darf nicht vor dem Rechnungsdatum liegen.",
};

/**
 * Explicit command: records that the money of a cancelled invoice went back.
 * LeonAid books no refund; the entry only closes the "Erstattung offen"
 * reminder.
 */
export function RefundDialog(props: SettlementDialogProps) {
  const cancellation = props.record?.cancellation;
  return props.record && cancellation?.refundOpen ? (
    <RefundForm
      key={props.record.invoice.id}
      {...props}
      cancellation={cancellation}
      record={props.record}
    />
  ) : null;
}

function RefundForm({
  cancellation,
  client,
  onChanged,
  onClose,
  record,
}: SettlementDialogProps & {
  readonly cancellation: NonNullable<InvoiceRecordResponse["cancellation"]>;
  readonly record: InvoiceRecordResponse;
}) {
  const { invoice } = record;
  const toast = useOptionalToast();
  const today = localIsoDate();
  // Money can have gone back before the cancellation was recorded here,
  // but not before the invoice existed.
  const minDate = isoDay(invoice.issuedAt);
  const [settledOn, setSettledOn] = useState(today);
  const [note, setNote] = useState("");
  const [dateError, setDateError] = useState<string>();
  const [serverError, setServerError] = useState<string>();
  const storageKey = refundCommandStorageKey(invoice.id);
  const received = formatMoney(
    cancellation.receivedMinor ?? 0,
    invoice.currency,
  );

  const refund = useMutation({
    mutationFn: () =>
      client.settleInvoiceCancellationRefund(
        invoice.actionId,
        invoice.id,
        { settledOn, note: note.trim() || null },
        {
          headers: {
            "Idempotency-Key": commandKey(storageKey, "poc095:refund"),
          },
        },
      ),
    onError(cause) {
      const message = actionErrorMessage(cause);
      const known = message.code ? refundErrors[message.code] : undefined;
      if (
        message.code === "invoice_refund_future_date" ||
        message.code === "invoice_refund_before_invoice"
      ) {
        setDateError(known);
        return;
      }
      if (message.code === "invoice_refund_already_settled") {
        // Someone else was faster: the list is behind, nothing to do here.
        forgetCommandKey(storageKey);
        toast?.show({ title: known!, tone: "info" });
        onChanged();
        onClose();
        return;
      }
      setServerError(known ?? message.message);
      if (message.conflict) onChanged();
    },
    onSuccess() {
      forgetCommandKey(storageKey);
      toast?.show({
        title: `Erstattung für ${invoice.number} als erledigt vermerkt.`,
        tone: "success",
      });
      onChanged();
      onClose();
    },
  });

  function submit() {
    if (refund.isPending) return;
    setServerError(undefined);
    if (!settledOn || settledOn < minDate || settledOn > today) {
      setDateError("Das Datum liegt zwischen dem Rechnungsdatum und heute.");
      return;
    }
    refund.mutate();
  }

  return (
    <Modal
      className="inv-dialog"
      description={`Erhalten: ${received} von ${record.buyerDisplayName}. LeonAid bucht keine Erstattung: Sie überweisen den Betrag außerhalb von LeonAid zurück. Dieser Vermerk schließt nur die Erinnerung „Erstattung offen“.`}
      footer={
        <>
          <Button disabled={refund.isPending} onClick={onClose} variant="ghost">
            Abbrechen
          </Button>
          <Button
            data-testid="settle-refund"
            loading={refund.isPending}
            onClick={submit}
            variant="primary"
          >
            Erstattung erledigt
          </Button>
        </>
      }
      onClose={() => {
        if (!refund.isPending) onClose();
      }}
      open
      title={`Erstattung für ${invoice.number} erledigt?`}
    >
      <form
        className="stack"
        data-testid="refund-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Field
          error={dateError}
          id={`refund-date-${invoice.id}`}
          label="Erstattet am"
        >
          <Input
            autoFocus
            data-testid="refund-date"
            max={today}
            min={minDate}
            onChange={(event) => {
              // Another body is another command: it gets its own key.
              forgetCommandKey(storageKey);
              setSettledOn(event.target.value);
              setDateError(undefined);
            }}
            type="date"
            value={settledOn}
          />
        </Field>
        <Field id={`refund-note-${invoice.id}`} label="Notiz" optional>
          <Input
            data-testid="refund-note"
            maxLength={500}
            onChange={(event) => {
              forgetCommandKey(storageKey);
              setNote(event.target.value);
            }}
            placeholder="z. B. Rücküberweisung vom Vereinskonto"
            value={note}
          />
        </Field>
        {serverError ? (
          <StatusMessage tone="error">{serverError}</StatusMessage>
        ) : null}
        <button hidden type="submit" />
      </form>
    </Modal>
  );
}

/**
 * Explicit command: takes "Erstattung erledigt" back, with a reason. The
 * refund is open again; the record keeps who set the marker and who withdrew
 * it.
 */
export function RefundWithdrawalDialog(props: SettlementDialogProps) {
  const cancellation = props.record?.cancellation;
  return props.record && cancellation?.refundSettledOn ? (
    <RefundWithdrawalForm
      key={props.record.invoice.id}
      {...props}
      record={props.record}
    />
  ) : null;
}

function RefundWithdrawalForm({
  client,
  onChanged,
  onClose,
  record,
}: SettlementDialogProps & { readonly record: InvoiceRecordResponse }) {
  const { invoice } = record;
  const toast = useOptionalToast();
  const [reason, setReason] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [serverError, setServerError] = useState<string>();
  const storageKey = refundWithdrawalCommandStorageKey(invoice.id);
  const tooShort = reason.trim().length < MIN_REASON;

  const withdrawal = useMutation({
    mutationFn: () =>
      client.withdrawInvoiceCancellationRefund(
        invoice.actionId,
        invoice.id,
        { reason: reason.trim() },
        {
          headers: {
            "Idempotency-Key": commandKey(
              storageKey,
              "poc095:refund-withdrawal",
            ),
          },
        },
      ),
    onError(cause) {
      const message = actionErrorMessage(cause);
      setServerError(message.message);
      if (message.conflict) onChanged();
    },
    onSuccess() {
      forgetCommandKey(storageKey);
      toast?.show({
        title: `Erstattung für ${invoice.number} ist wieder offen.`,
        tone: "success",
      });
      onChanged();
      onClose();
    },
  });

  function submit() {
    if (withdrawal.isPending) return;
    setSubmitted(true);
    setServerError(undefined);
    if (tooShort) return;
    withdrawal.mutate();
  }

  return (
    <Modal
      className="inv-dialog"
      description="Der Vermerk „Erstattung erledigt“ wird zurückgenommen und die Rechnung zeigt wieder „Erstattung offen“. Wer den Vermerk gesetzt und wer ihn zurückgenommen hat, bleibt bei der Rechnung sichtbar."
      footer={
        <>
          <Button
            disabled={withdrawal.isPending}
            onClick={onClose}
            variant="ghost"
          >
            Abbrechen
          </Button>
          <Button
            data-testid="withdraw-refund"
            loading={withdrawal.isPending}
            onClick={submit}
            variant="danger"
          >
            Erstattung zurücknehmen
          </Button>
        </>
      }
      onClose={() => {
        if (!withdrawal.isPending) onClose();
      }}
      open
      role="alertdialog"
      title={`Erstattung für ${invoice.number} zurücknehmen?`}
    >
      <form
        className="stack"
        data-testid="refund-withdrawal-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Field
          error={
            submitted && tooShort
              ? "Bitte nennen Sie den Grund mit mindestens acht Zeichen."
              : undefined
          }
          id={`refund-withdrawal-reason-${invoice.id}`}
          label="Grund der Rücknahme"
          required
        >
          <Textarea
            autoFocus
            data-testid="refund-withdrawal-reason"
            maxLength={500}
            onChange={(event) => {
              // Another body is another command: it gets its own key.
              forgetCommandKey(storageKey);
              setReason(event.target.value);
            }}
            rows={3}
            value={reason}
          />
        </Field>
        {serverError ? (
          <StatusMessage tone="error">{serverError}</StatusMessage>
        ) : null}
      </form>
    </Modal>
  );
}
