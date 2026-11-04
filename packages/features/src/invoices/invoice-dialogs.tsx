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
  settlementCommandStorageKey,
} from "./invoice-model";

interface SettlementDialogProps {
  readonly client: LeonAidApiClient;
  /** The invoice the dialog is for; null keeps it closed. */
  readonly record: InvoiceRecordResponse | null;
  readonly onClose: () => void;
  readonly onChanged: () => void;
}

/** Explicit command: records the exact full payment of an open invoice. */
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
  const toast = useOptionalToast();
  const [amount, setAmount] = useState("");
  const [receivedOn, setReceivedOn] = useState(localIsoDate);
  const [reference, setReference] = useState("");
  const [amountError, setAmountError] = useState<string>();
  const [dateError, setDateError] = useState<string>();
  const [serverError, setServerError] = useState<string>();
  const storageKey = settlementCommandStorageKey(invoice.id, "payment");
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
    onSuccess() {
      forgetCommandKey(storageKey);
      toast?.show({
        title: `Zahlung für ${invoice.number} erfasst.`,
        tone: "success",
      });
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
    if (minor !== record.openMinor) {
      setAmountError(
        `Nur die exakte Vollzahlung von ${open} kann erfasst werden. Eingegangen sind ${formatMoney(minor, invoice.currency)}. Klären Sie die Differenz mit dem Sponsor und erfassen Sie danach den vollen Betrag.`,
      );
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
          hint="Nur vollständige Zahlungen. Teilzahlungen sind im Pilot nicht vorgesehen."
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
        {serverError ? (
          <StatusMessage tone="error">{serverError}</StatusMessage>
        ) : null}
        <button hidden type="submit" />
      </form>
    </Modal>
  );
}

const MIN_REASON = 8;

/**
 * Explicit command: cancels an issued invoice for good. The record and its
 * PDF stay; a correction is a new, separately numbered invoice.
 */
export function CancellationDialog(props: SettlementDialogProps) {
  return props.record ? (
    <CancellationForm
      key={props.record.invoice.id}
      {...props}
      record={props.record}
    />
  ) : null;
}

function CancellationForm({
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
  const storageKey = settlementCommandStorageKey(invoice.id, "cancellation");

  const cancellation = useMutation({
    mutationFn: () =>
      client.cancelInvoice(
        invoice.actionId,
        invoice.id,
        { reason: reason.trim() },
        {
          headers: {
            "Idempotency-Key": commandKey(storageKey, "poc095:cancellation"),
          },
        },
      ),
    onError(cause) {
      setServerError(actionErrorMessage(cause).message);
    },
    onSuccess() {
      forgetCommandKey(storageKey);
      toast?.show({ title: `${invoice.number} storniert.`, tone: "success" });
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
      description="Die Rechnung bleibt mit Nummer, Daten und PDF erhalten und wird als storniert markiert. Eine Korrektur erhält eine neue Rechnungsnummer."
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
        {serverError ? (
          <StatusMessage tone="error">{serverError}</StatusMessage>
        ) : null}
      </form>
    </Modal>
  );
}
