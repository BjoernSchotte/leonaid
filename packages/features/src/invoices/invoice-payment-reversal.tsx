import { useMutation } from "@tanstack/react-query";
import { Undo2 } from "lucide-react";
import { useState } from "react";

import type {
  InvoicePaymentResponse,
  InvoiceRecordResponse,
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
import { formatMoney, shortDate } from "./invoice-format";
import {
  commandKey,
  forgetCommandKey,
  invoiceSettlement,
  reversalCommandStorageKey,
} from "./invoice-model";

const MIN_REASON = 8;

interface PaymentReversalDialogProps {
  readonly client: LeonAidApiClient;
  /** The invoice of the entry; null keeps the dialog closed. */
  readonly record: InvoiceRecordResponse | null;
  readonly paymentId: string | null;
  readonly onClose: () => void;
  readonly onChanged: () => void;
}

/**
 * Explicit command: reverses one payment entry. The entry stays visible,
 * struck through, and no longer counts toward the paid sum.
 */
export function PaymentReversalDialog(props: PaymentReversalDialogProps) {
  const payment = props.record
    ? invoiceSettlement(props.record).active.find(
        (item) => item.id === props.paymentId,
      )
    : undefined;
  return props.record && payment ? (
    <PaymentReversalForm
      key={payment.id}
      {...props}
      payment={payment}
      record={props.record}
    />
  ) : null;
}

function PaymentReversalForm({
  client,
  onChanged,
  onClose,
  payment,
  record,
}: PaymentReversalDialogProps & {
  readonly payment: InvoicePaymentResponse;
  readonly record: InvoiceRecordResponse;
}) {
  const { invoice } = record;
  const toast = useOptionalToast();
  const [reason, setReason] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [serverError, setServerError] = useState<string>();
  const [openedVersion] = useState(() => invoiceSettlement(record).version);
  const storageKey = reversalCommandStorageKey(payment.id);
  const amount = formatMoney(payment.amountMinor, payment.currency);
  const received = shortDate(payment.receivedOn);

  const reversal = useMutation({
    mutationFn: () =>
      client.reverseInvoicePayment(
        invoice.actionId,
        invoice.id,
        payment.id,
        {
          reason: reason.trim(),
          expectedSettlementVersion: openedVersion,
        },
        {
          headers: {
            "Idempotency-Key": commandKey(storageKey, "invoice:reversal"),
          },
        },
      ),
    onError(cause) {
      setServerError(actionErrorMessage(cause).message);
    },
    onSuccess() {
      forgetCommandKey(storageKey);
      toast?.show({
        title: `Zahlung über ${amount} zurückgebucht.`,
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
    if (reversal.isPending) return;
    setSubmitted(true);
    setServerError(undefined);
    if (tooShort) return;
    reversal.mutate();
  }

  return (
    <Modal
      className="inv-dialog"
      description={`${amount}, eingegangen am ${received}. Der Eintrag bleibt in der Historie erhalten und zählt nicht mehr zum bezahlten Betrag. Der offene Betrag steigt um ${amount}.`}
      footer={
        <>
          <Button
            disabled={reversal.isPending}
            onClick={onClose}
            variant="ghost"
          >
            Abbrechen
          </Button>
          <Button
            data-testid="reverse-payment"
            icon={Undo2}
            loading={reversal.isPending}
            onClick={submit}
            variant="danger"
          >
            Zurückbuchen
          </Button>
        </>
      }
      onClose={() => {
        if (!reversal.isPending) onClose();
      }}
      open
      role="alertdialog"
      title={`Zahlung für ${invoice.number} zurückbuchen?`}
    >
      <form
        className="stack"
        data-testid="reversal-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Field
          error={error}
          hint="Erscheint beim Zahlungseintrag und in der Historie."
          id={`reversal-reason-${payment.id}`}
          label="Grund der Rückbuchung"
        >
          <Textarea
            autoFocus
            data-testid="reversal-reason"
            maxLength={500}
            onChange={(event) => setReason(event.target.value)}
            placeholder="z. B. Lastschrift von der Bank zurückgegeben"
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
