import { useMutation } from "@tanstack/react-query";
import { Ban, Undo2 } from "lucide-react";
import { useState } from "react";

import type { DonationResponse, LeonAidApiClient } from "@leonaid/api-client";
import {
  Button,
  Field,
  Input,
  Modal,
  StatusMessage,
  Textarea,
  useOptionalToast,
} from "@leonaid/ui";

import {
  amountInput,
  formatDate,
  formatMoney,
  isoDay,
  localIsoDate,
  parseAmountMinor,
} from "../invoices/invoice-format";
import { commandKey, forgetCommandKey } from "../invoices/invoice-model";
import {
  donationCommandStorageKey,
  donationCreateStorageKey,
  donationErrorMessage,
  MAX_PAYMENT_MINOR,
  MAX_PLEDGE_MINOR,
  MIN_PLEDGE_MINOR,
  MIN_REASON,
  withPeriod,
} from "./donation-model";

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type CreateField =
  | "name"
  | "streetLine1"
  | "postalCode"
  | "city"
  | "email"
  | "amount"
  | "note";

const emptyCreate: Readonly<Record<CreateField, string>> = {
  name: "",
  streetLine1: "",
  postalCode: "",
  city: "",
  email: "",
  amount: "",
  note: "",
};

interface CreateDonationDialogProps {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  readonly open: boolean;
  /** The body that receives the donation and issues its documents. */
  readonly receivingBodyName: string;
  readonly onClose: () => void;
  readonly onChanged: () => void;
}

/**
 * Explicit command: records a pledged donation. The server gives it its
 * number and starts the pledge PDF in the same step.
 */
export function CreateDonationDialog(props: CreateDonationDialogProps) {
  // A fresh form per opening.
  return props.open ? <CreateDonationForm {...props} /> : null;
}

function CreateDonationForm({
  actionId,
  client,
  onChanged,
  onClose,
  receivingBodyName,
}: CreateDonationDialogProps) {
  const toast = useOptionalToast();
  const [values, setValues] = useState(emptyCreate);
  const [errors, setErrors] = useState<Partial<Record<CreateField, string>>>(
    {},
  );
  const [serverError, setServerError] = useState<string>();
  const storageKey = donationCreateStorageKey(actionId);

  function set(field: CreateField, value: string) {
    // Another body is another command: it gets its own key.
    forgetCommandKey(storageKey);
    setValues((previous) => ({ ...previous, [field]: value }));
    setErrors((previous) => ({ ...previous, [field]: undefined }));
  }

  const create = useMutation({
    mutationFn: (pledgedMinor: number) =>
      client.createDonation(
        actionId,
        {
          donor: {
            name: values.name.trim(),
            streetLine1: values.streetLine1.trim(),
            postalCode: values.postalCode.trim(),
            city: values.city.trim(),
            email: values.email.trim() || null,
          },
          pledgedMinor,
          note: values.note.trim() || null,
        },
        {
          headers: {
            "Idempotency-Key": commandKey(storageKey, "donation:create"),
          },
        },
      ),
    onError(cause) {
      const message = donationErrorMessage(cause);
      setServerError(message.message);
      if (message.conflict) onChanged();
    },
    onSuccess(donation) {
      forgetCommandKey(storageKey);
      toast?.show(
        donation.replayed
          ? {
              title: "Diese Spende war bereits erfasst.",
              description: `Es wurde keine zweite Spende angelegt (${donation.number}).`,
              tone: "info",
            }
          : {
              title: `Spende ${donation.number} erfasst.`,
              description: "Die Spendenzusage wird als PDF erzeugt.",
              tone: "success",
            },
      );
      onChanged();
      onClose();
    },
  });

  function submit() {
    if (create.isPending) return;
    setServerError(undefined);
    const next: Partial<Record<CreateField, string>> = {};
    if (values.name.trim().length < 2) {
      next.name = "Bitte den Namen des Spenders eingeben.";
    }
    if (values.streetLine1.trim().length < 2) {
      next.streetLine1 = "Bitte Straße und Hausnummer eingeben.";
    }
    if (values.postalCode.trim().length < 2) {
      next.postalCode = "Bitte die Postleitzahl eingeben.";
    }
    if (values.city.trim().length < 2) {
      next.city = "Bitte den Ort eingeben.";
    }
    if (values.email.trim() && !EMAIL.test(values.email.trim())) {
      next.email = "Bitte eine gültige E-Mail-Adresse eingeben.";
    }
    const minor = parseAmountMinor(values.amount);
    if (minor === null) {
      next.amount = "Bitte einen Betrag wie 50,00 eingeben.";
    } else if (minor < MIN_PLEDGE_MINOR || minor > MAX_PLEDGE_MINOR) {
      next.amount = `Der Betrag liegt zwischen ${formatMoney(MIN_PLEDGE_MINOR, "EUR")} und ${formatMoney(MAX_PLEDGE_MINOR, "EUR")}.`;
    }
    setErrors(next);
    if (Object.keys(next).length > 0 || minor === null) return;
    create.mutate(minor);
  }

  return (
    <Modal
      className="inv-dialog"
      description={`Die Spende erhält sofort eine Nummer und eine Spendenzusage als PDF. ${withPeriod(`Sie geht an ${receivingBodyName}`)}`}
      footer={
        <>
          <Button disabled={create.isPending} onClick={onClose} variant="ghost">
            Abbrechen
          </Button>
          <Button
            data-testid="create-donation"
            loading={create.isPending}
            onClick={submit}
            variant="primary"
          >
            Spende erfassen
          </Button>
        </>
      }
      onClose={() => {
        if (!create.isPending) onClose();
      }}
      open
      title="Spende erfassen"
    >
      <form
        className="stack"
        data-testid="donation-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Field
          error={errors.name}
          hint="Person oder Firma, wie sie auf der Zuwendungsbestätigung stehen soll."
          id="donation-donor-name"
          label="Name des Spenders"
        >
          <Input
            autoComplete="off"
            autoFocus
            data-testid="donation-donor-name"
            maxLength={200}
            onChange={(event) => set("name", event.target.value)}
            value={values.name}
          />
        </Field>
        <Field
          error={errors.streetLine1}
          id="donation-donor-street"
          label="Straße und Hausnummer"
        >
          <Input
            autoComplete="off"
            data-testid="donation-donor-street"
            maxLength={200}
            onChange={(event) => set("streetLine1", event.target.value)}
            value={values.streetLine1}
          />
        </Field>
        <Field
          error={errors.postalCode}
          id="donation-donor-postal-code"
          label="Postleitzahl"
        >
          <Input
            autoComplete="off"
            data-testid="donation-donor-postal-code"
            maxLength={20}
            onChange={(event) => set("postalCode", event.target.value)}
            value={values.postalCode}
          />
        </Field>
        <Field error={errors.city} id="donation-donor-city" label="Ort">
          <Input
            autoComplete="off"
            data-testid="donation-donor-city"
            maxLength={120}
            onChange={(event) => set("city", event.target.value)}
            value={values.city}
          />
        </Field>
        <Field
          error={errors.email}
          hint="An diese Adresse können Sie die Spendenzusage senden."
          id="donation-donor-email"
          label="E-Mail"
          optional
        >
          <Input
            autoComplete="off"
            data-testid="donation-donor-email"
            maxLength={320}
            onChange={(event) => set("email", event.target.value)}
            type="email"
            value={values.email}
          />
        </Field>
        <Field
          error={errors.amount}
          hint="Zugesagter Betrag, von 1,00 € bis 1.000.000,00 €."
          id="donation-amount"
          label="Betrag in €"
        >
          <Input
            autoComplete="off"
            data-testid="donation-amount"
            inputMode="decimal"
            onChange={(event) => set("amount", event.target.value)}
            placeholder="50,00"
            value={values.amount}
          />
        </Field>
        <Field id="donation-note" label="Notiz" optional>
          <Input
            data-testid="donation-note"
            maxLength={500}
            onChange={(event) => set("note", event.target.value)}
            placeholder="z. B. beim Sommerfest zugesagt"
            value={values.note}
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

interface DonationDialogProps {
  readonly client: LeonAidApiClient;
  /** The donation the dialog is for; null keeps it closed. */
  readonly donation: DonationResponse | null;
  readonly onClose: () => void;
  readonly onChanged: () => void;
}

/**
 * Explicit command: records the one payment of a donation. The amount
 * starts as the pledge and may differ from it in either direction.
 */
export function DonationPaymentDialog(props: DonationDialogProps) {
  return props.donation?.status === "pledged" ? (
    <DonationPaymentForm
      key={props.donation.id}
      {...props}
      donation={props.donation}
    />
  ) : null;
}

/** What the typed amount means against the pledge, before it is recorded. */
function differenceHint(minor: number | null, donation: DonationResponse) {
  const fixed =
    "Der Betrag darf von der Zusage abweichen. Eine zweite Teilzahlung erfassen Sie als eigene Spende.";
  if (minor === null || minor <= 0) return fixed;
  const difference = minor - donation.pledgedMinor;
  if (difference === 0) return `Entspricht der Zusage. ${fixed}`;
  const amount = formatMoney(Math.abs(difference), donation.currency);
  return `${amount} ${difference > 0 ? "mehr" : "weniger"} als zugesagt. ${fixed}`;
}

function DonationPaymentForm({
  client,
  donation,
  onChanged,
  onClose,
}: DonationDialogProps & { readonly donation: DonationResponse }) {
  const toast = useOptionalToast();
  const [amount, setAmount] = useState(() =>
    amountInput(donation.pledgedMinor),
  );
  const [receivedOn, setReceivedOn] = useState(localIsoDate);
  const [note, setNote] = useState("");
  const [amountError, setAmountError] = useState<string>();
  const [dateError, setDateError] = useState<string>();
  const [serverError, setServerError] = useState<string>();
  const storageKey = donationCommandStorageKey("payment", donation.id);
  const pledged = formatMoney(donation.pledgedMinor, donation.currency);
  const minDate = isoDay(donation.pledgedAt);
  const today = localIsoDate();
  const dateRule = `Das Eingangsdatum liegt zwischen dem Tag der Zusage (${formatDate(minDate)}) und heute.`;

  const payment = useMutation({
    mutationFn: (amountMinor: number) =>
      client.recordDonationPayment(
        donation.actionId,
        donation.id,
        { amountMinor, receivedOn, note: note.trim() || null },
        {
          headers: {
            "Idempotency-Key": commandKey(storageKey, "donation:payment"),
          },
        },
      ),
    onError(cause) {
      const message = donationErrorMessage(cause);
      if (
        message.code === "donation_payment_before_pledge" ||
        message.code === "donation_payment_future_date"
      ) {
        setDateError(message.message);
        return;
      }
      if (
        message.code === "donation_payment_already_recorded" ||
        message.code === "donation_cancelled"
      ) {
        // Someone else was faster: the list is behind, nothing to do here.
        forgetCommandKey(storageKey);
        toast?.show({ title: message.message, tone: "info" });
        onChanged();
        onClose();
        return;
      }
      setServerError(message.message);
      if (message.conflict) onChanged();
    },
    onSuccess(result) {
      forgetCommandKey(storageKey);
      toast?.show(
        result.replayed
          ? {
              title: "Diese Zahlung war bereits erfasst.",
              description: `Für ${donation.number} wurde kein zweiter Eintrag angelegt.`,
              tone: "info",
            }
          : {
              title: `Zahlung für ${donation.number} erfasst.`,
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
        `Bitte einen Betrag wie ${pledged.replace(/\s?€/, "")} eingeben.`,
      );
      return;
    }
    if (minor <= 0) {
      setAmountError("Der eingegangene Betrag muss größer als 0,00 € sein.");
      return;
    }
    if (minor > MAX_PAYMENT_MINOR) {
      setAmountError(
        `Der Betrag darf höchstens ${formatMoney(MAX_PAYMENT_MINOR, donation.currency)} sein.`,
      );
      return;
    }
    if (!receivedOn || receivedOn < minDate || receivedOn > today) {
      setDateError(dateRule);
      return;
    }
    payment.mutate(minor);
  }

  return (
    <Modal
      className="inv-dialog"
      description={`Zugesagt: ${pledged} von ${donation.donor.name}`}
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
            data-testid="record-donation-payment"
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
      title={`Zahlung für ${donation.number} erfassen`}
    >
      <form
        className="stack"
        data-testid="donation-payment-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Field
          error={amountError}
          hint={differenceHint(parseAmountMinor(amount), donation)}
          id={`donation-pay-amount-${donation.id}`}
          label="Eingegangener Betrag in €"
        >
          <Input
            autoComplete="off"
            autoFocus
            data-testid="donation-payment-amount"
            inputMode="decimal"
            onChange={(event) => {
              // Another body is another command: it gets its own key.
              forgetCommandKey(storageKey);
              setAmount(event.target.value);
              setAmountError(undefined);
            }}
            placeholder={pledged.replace(/\s?€/, "")}
            value={amount}
          />
        </Field>
        <Field
          error={dateError}
          hint="Nicht vor dem Tag der Zusage und nicht in der Zukunft."
          id={`donation-pay-date-${donation.id}`}
          label="Eingangsdatum"
        >
          <Input
            data-testid="donation-payment-date"
            max={today}
            min={minDate}
            onChange={(event) => {
              forgetCommandKey(storageKey);
              setReceivedOn(event.target.value);
              setDateError(undefined);
            }}
            type="date"
            value={receivedOn}
          />
        </Field>
        <Field id={`donation-pay-note-${donation.id}`} label="Notiz" optional>
          <Input
            data-testid="donation-payment-note"
            maxLength={500}
            onChange={(event) => {
              forgetCommandKey(storageKey);
              setNote(event.target.value);
            }}
            placeholder="z. B. Überweisung vom 5. Dezember"
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

/** The words and the server call of the two commands that take a reason. */
const reasonCommands = {
  withdrawal: {
    storage: "payment-withdrawal",
    keyPrefix: "donation:payment-withdrawal",
    title: (number: string) => `Zahlung für ${number} zurücknehmen?`,
    description:
      "Die erfasste Zahlung wird zurückgenommen und die Spende ist wieder offen. Wer die Zahlung erfasst und wer sie zurückgenommen hat, bleibt bei der Spende sichtbar.",
    label: "Grund der Rücknahme",
    hint: "Erscheint in der Historie der Spende.",
    placeholder: "z. B. Zahlung der falschen Spende zugeordnet",
    submit: "Zahlung zurücknehmen",
    icon: Undo2,
    formTestId: "donation-withdrawal-form",
    reasonTestId: "donation-withdrawal-reason",
    submitTestId: "withdraw-donation-payment",
    done: (number: string) => `Zahlung für ${number} zurückgenommen.`,
  },
  cancellation: {
    storage: "cancellation",
    keyPrefix: "donation:cancellation",
    title: (number: string) => `Spende ${number} stornieren?`,
    description:
      "Die Spende bleibt mit Nummer, Daten und Spendenzusage erhalten und wird als storniert markiert. Sie zählt nicht mehr zu den offenen Zusagen.",
    label: "Grund der Stornierung",
    hint: "Erscheint in der Historie der Spende.",
    placeholder: "z. B. Spender hat die Zusage zurückgezogen",
    submit: "Spende stornieren",
    icon: Ban,
    formTestId: "donation-cancellation-form",
    reasonTestId: "donation-cancellation-reason",
    submitTestId: "cancel-donation",
    done: (number: string) => `Spende ${number} storniert.`,
  },
} as const;

type ReasonCommand = keyof typeof reasonCommands;

/** Explicit command: takes the recorded payment back, with a reason. */
export function DonationPaymentWithdrawalDialog(props: DonationDialogProps) {
  return props.donation?.status === "paid" ? (
    <ReasonForm
      key={props.donation.id}
      {...props}
      command="withdrawal"
      donation={props.donation}
    />
  ) : null;
}

/** Explicit command: cancels an unpaid donation for good, with a reason. */
export function DonationCancellationDialog(props: DonationDialogProps) {
  return props.donation?.status === "pledged" ? (
    <ReasonForm
      key={props.donation.id}
      {...props}
      command="cancellation"
      donation={props.donation}
    />
  ) : null;
}

function ReasonForm({
  client,
  command,
  donation,
  onChanged,
  onClose,
}: DonationDialogProps & {
  readonly command: ReasonCommand;
  readonly donation: DonationResponse;
}) {
  const words = reasonCommands[command];
  const toast = useOptionalToast();
  const [reason, setReason] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [serverError, setServerError] = useState<string>();
  const storageKey = donationCommandStorageKey(words.storage, donation.id);
  const tooShort = reason.trim().length < MIN_REASON;

  const mutation = useMutation({
    mutationFn: () => {
      const body = { reason: reason.trim() };
      const options = {
        headers: {
          "Idempotency-Key": commandKey(storageKey, words.keyPrefix),
        },
      };
      return command === "withdrawal"
        ? client.withdrawDonationPayment(
            donation.actionId,
            donation.id,
            body,
            options,
          )
        : client.cancelDonation(donation.actionId, donation.id, body, options);
    },
    onError(cause) {
      const message = donationErrorMessage(cause);
      setServerError(message.message);
      // A refusal means the list is behind (paid or cancelled meanwhile).
      if (message.conflict) onChanged();
    },
    onSuccess() {
      forgetCommandKey(storageKey);
      toast?.show({ title: words.done(donation.number), tone: "success" });
      onChanged();
      onClose();
    },
  });

  function submit() {
    if (mutation.isPending) return;
    setSubmitted(true);
    setServerError(undefined);
    if (tooShort) return;
    mutation.mutate();
  }

  return (
    <Modal
      className="inv-dialog"
      description={words.description}
      footer={
        <>
          <Button
            disabled={mutation.isPending}
            onClick={onClose}
            variant="ghost"
          >
            Abbrechen
          </Button>
          <Button
            data-testid={words.submitTestId}
            icon={words.icon}
            loading={mutation.isPending}
            onClick={submit}
            variant="danger"
          >
            {words.submit}
          </Button>
        </>
      }
      onClose={() => {
        if (!mutation.isPending) onClose();
      }}
      open
      role="alertdialog"
      title={words.title(donation.number)}
    >
      <form
        className="stack"
        data-testid={words.formTestId}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Field
          error={
            submitted && tooShort
              ? `Bitte einen Grund mit mindestens ${MIN_REASON} Zeichen angeben.`
              : undefined
          }
          hint={words.hint}
          id={`donation-${command}-reason-${donation.id}`}
          label={words.label}
          required
        >
          <Textarea
            autoFocus
            data-testid={words.reasonTestId}
            maxLength={500}
            onChange={(event) => {
              // Another body is another command: it gets its own key.
              forgetCommandKey(storageKey);
              setReason(event.target.value);
            }}
            placeholder={words.placeholder}
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
