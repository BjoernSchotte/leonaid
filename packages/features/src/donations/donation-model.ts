import {
  ApiError,
  type DonationDeliveryResponse,
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

/** In-flight states of a pledge mail; the list polls while one is open. */
export function pledgeDeliveryInProgress(delivery: DonationDeliveryResponse) {
  return (
    delivery.status === "queued" ||
    delivery.status === "sending" ||
    delivery.status === "retrying"
  );
}

/** The list polls while a pledge PDF renders or a pledge mail is on its way. */
export function donationInFlight(donation: DonationResponse) {
  return (
    donation.pledgeDocument?.status === "pending" ||
    donation.pledgeDeliveries.some(pledgeDeliveryInProgress)
  );
}

export interface DonationRow {
  readonly id: string;
  readonly donation: DonationResponse;
  readonly status: DonationStatus;
  /** State of the newest pledge mail. */
  readonly dispatch: InvoiceDispatch;
}

export function donationRows(
  donations: readonly DonationResponse[],
): DonationRow[] {
  return donations.map((donation) => {
    const latest = donation.pledgeDeliveries[0];
    return {
      id: donation.id,
      donation,
      status: donation.status,
      dispatch: !latest
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
/** Reasons of a withdrawal or cancellation (DonationReasonRequest). */
export const MIN_REASON = 8;

export const RECEIVING_BODY_MISSING =
  "In „Organisation & Recht“ fehlt der Teil „Spenden“ mit der empfangenden Körperschaft. Ohne ihn kann keine Spende erfasst werden.";

/** German copy for the refusals of the donation commands. */
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
    | "pledge-delivery-retry",
  id: string,
) => `leonaid.donation-${kind}-command.${id}`;

export const donationCreateStorageKey = (actionId: string) =>
  `leonaid.donation-create-command.${actionId}`;
