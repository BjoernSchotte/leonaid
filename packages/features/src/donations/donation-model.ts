import {
  ApiError,
  type DonationDeliveryResponse,
  type DonationReceiptResponse,
  type DonationResponse,
} from "@leonaid/api-client";

import { actionErrorMessage } from "../action-admin/errors";
import type { InvoiceDispatch } from "../invoices/invoice-model";

export type DonationStatus = DonationResponse["status"];

/** "Offen" is a pledge without a recorded payment. */
export const donationStatusLabels: Readonly<Record<DonationStatus, string>> = {
  pledged: "Offen",
  paid: "Bezahlt",
  cancelled: "Storniert",
};

export const DONATION_STATUSES: readonly DonationStatus[] = [
  "pledged",
  "paid",
  "cancelled",
];

export const donationSourceLabels: Readonly<
  Record<DonationResponse["source"], string>
> = {
  public_form: "Öffentliches Formular",
  admin: "Verwaltung",
  acquisition: "Akquise",
};

/** Whether a donation has a valid receipt ("Zuwendungsbestätigung"). */
export type DonationReceiptState = "issued" | "none";

export const DONATION_RECEIPT_STATES: readonly DonationReceiptState[] = [
  "issued",
  "none",
];

export const donationReceiptStateLabels: Readonly<
  Record<DonationReceiptState, string>
> = {
  issued: "Bestätigt",
  none: "Nicht bestätigt",
};

export type DonationReceiptSigning = DonationReceiptResponse["signing"];
export type DonationReceiptEvidence = NonNullable<
  DonationReceiptResponse["void"]
>["evidence"];

/** What happened to the paper the donor holds, in display order. */
export const DONATION_RECEIPT_EVIDENCE: readonly DonationReceiptEvidence[] = [
  "original_returned",
  "tax_office_informed",
];

export const donationReceiptEvidenceLabels: Readonly<
  Record<DonationReceiptEvidence, string>
> = {
  original_returned: "Das Original liegt uns wieder vor",
  tax_office_informed: "Das Finanzamt des Spenders ist informiert",
};

/** The one receipt of a donation that is not void, if any. */
export function validDonationReceipt(
  donation: DonationResponse,
): DonationReceiptResponse | undefined {
  return donation.receipts.find((receipt) => receipt.void === null);
}

/**
 * True once the last day the receiving body's notice carries a receipt
 * (§ 63 Abs. 5 AO) has passed. Both are ISO days, so they compare as text.
 */
export function donationReceiptNoticeExpired(
  validUntil: string | null,
  today: string,
) {
  return validUntil !== null && validUntil < today;
}

/** In-flight states of a donation mail; the list polls while one is open. */
export function pledgeDeliveryInProgress(delivery: DonationDeliveryResponse) {
  return (
    delivery.status === "queued" ||
    delivery.status === "sending" ||
    delivery.status === "retrying"
  );
}

/**
 * The list polls while a pledge or receipt PDF renders or one of their
 * mails is on its way.
 */
export function donationInFlight(donation: DonationResponse) {
  return (
    donation.pledgeDocument.status === "pending" ||
    donation.pledgeDeliveries.some(pledgeDeliveryInProgress) ||
    donation.receipts.some(
      (receipt) =>
        receipt.document.status === "pending" ||
        receipt.deliveries.some(pledgeDeliveryInProgress),
    )
  );
}

export interface DonationRow {
  readonly id: string;
  readonly donation: DonationResponse;
  readonly status: DonationStatus;
  /** "issued" while the donation has a valid receipt. */
  readonly receipt: DonationReceiptState;
  /**
   * State of the newest pledge mail. A failed newest mail of the valid
   * receipt counts as "failed" too, so the row shows it.
   */
  readonly dispatch: InvoiceDispatch;
}

export function donationRows(
  donations: readonly DonationResponse[],
): DonationRow[] {
  return donations.map((donation) => {
    const latest = donation.pledgeDeliveries[0];
    const receipt = validDonationReceipt(donation);
    return {
      id: donation.id,
      donation,
      status: donation.status,
      receipt: receipt ? "issued" : "none",
      dispatch:
        receipt?.deliveries[0]?.status === "failed"
          ? "failed"
          : !latest
            ? "not_sent"
            : latest.status === "sent"
              ? "sent"
              : latest.status === "failed"
                ? "failed"
                : "in_progress",
    };
  });
}

/** The amount limits of a pledge (CreateDonationRequest.pledgedMinor). */
export const MIN_PLEDGE_MINOR = 100;
export const MAX_PLEDGE_MINOR = 100_000_000;
/** The upper limit of a recorded payment (RecordDonationPaymentRequest). */
export const MAX_PAYMENT_MINOR = 1_000_000_000;
/** Reasons of a withdrawal, a cancellation or a voided receipt. */
export const MIN_REASON = 8;

/** Named where the server gives no display name of who acted. */
export const FINANCE_ROLE = "Berechtigte Finanzrolle";

export const RECEIVING_BODY_MISSING =
  "In „Rechtliches“ fehlt der Teil „Spenden“ mit der empfangenden Körperschaft. Ohne ihn kann keine Spende erfasst werden.";

export const RECEIPT_BLOCKS_WITHDRAWAL =
  "Für diese Zahlung ist eine Zuwendungsbestätigung ausgestellt. Erklären Sie sie zuerst für ungültig.";

/**
 * German copy for the refusals of the donation commands. Not listed on
 * purpose: `donation_receipt_notice_expired`, whose server message names the
 * notice, its last day and where to renew it.
 */
const donationErrors: Readonly<Record<string, string>> = {
  donation_capability_disabled:
    "Für diese Aktion sind Spenden nicht aktiviert.",
  donation_receiving_body_missing: RECEIVING_BODY_MISSING,
  donation_payment_already_recorded:
    "Für diese Spende ist bereits eine Zahlung erfasst.",
  donation_payment_before_pledge:
    "Das Eingangsdatum darf nicht vor dem Tag der Zusage liegen.",
  donation_payment_future_date:
    "Das Eingangsdatum darf nicht in der Zukunft liegen.",
  donation_cancelled: "Diese Spende ist storniert.",
  donation_paid:
    "Eine bezahlte Spende kann nicht storniert werden. Nehmen Sie zuerst die Zahlung zurück.",
  donation_donor_email_missing:
    "Für den Versand fehlt die E-Mail-Adresse des Spenders.",
  donation_pledge_document_not_ready:
    "Die Spendenzusage wird noch erzeugt. Versuchen Sie es gleich erneut.",
  donation_receipt_requires_payment:
    "Eine Zuwendungsbestätigung gibt es erst nach dem Zahlungseingang.",
  donation_receipt_already_issued:
    "Für diese Spende ist bereits eine Zuwendungsbestätigung ausgestellt.",
  donation_receipt_already_void:
    "Diese Zuwendungsbestätigung ist bereits für ungültig erklärt.",
  donation_receipt_issued: RECEIPT_BLOCKS_WITHDRAWAL,
  donation_receipt_signed_by_hand:
    "Diese Zuwendungsbestätigung gilt nur mit Unterschrift und wird nicht per E-Mail gesendet.",
  donation_receipt_void:
    "Diese Zuwendungsbestätigung ist für ungültig erklärt und wird nicht mehr gesendet.",
  donation_receipt_document_not_ready:
    "Die Zuwendungsbestätigung wird noch erzeugt. Versuchen Sie es gleich erneut.",
};

/**
 * `actionErrorMessage` (fresh-login redirect, support code) with the
 * donation refusals in German.
 */
export function donationErrorMessage(cause: unknown) {
  const message = actionErrorMessage(cause);
  const known = message.code ? donationErrors[message.code] : undefined;
  return known ? { ...message, message: known } : message;
}

export function isCapabilityDisabled(error: unknown) {
  return (
    error instanceof ApiError &&
    error.detail.code === "donation_capability_disabled"
  );
}

export const donationCommandStorageKey = (
  kind:
    | "payment"
    | "payment-withdrawal"
    | "cancellation"
    | "pledge-delivery"
    | "receipt"
    | "receipt-void"
    | "receipt-delivery",
  /** The donation; for the receipt commands that name one, the receipt. */
  id: string,
) => `leonaid.donation-${kind}-command.${id}`;

export const donationCreateStorageKey = (actionId: string) =>
  `leonaid.donation-create-command.${actionId}`;

/** Ends a sentence once: a short date ("10.11.") and a name ("e. V.")
 * already end with a period. */
export function withPeriod(text: string) {
  return text.endsWith(".") ? text : `${text}.`;
}
