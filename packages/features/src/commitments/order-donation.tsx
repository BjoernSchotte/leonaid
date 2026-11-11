/*
 * The extra donation of an order (specs/mails-documents-donations-push
 * §8.6): an amount on the order, and from the moment the order is binding a
 * donation of its own with a number and a state. Never part of the invoice.
 */
import type {
  CommitmentDonationResponse,
  CommitmentRecordResponse,
} from "@leonaid/api-client";

import { donationHref } from "../invoices/invoice-ledgers";
import { parseAmountMinor } from "../invoices/invoice-format";
import { euro } from "./order-format";

export const DONATION_MIN_MINOR = 100;
export const DONATION_MAX_MINOR = 1_000_000;

export type DonationInput =
  | { readonly kind: "empty" }
  | { readonly kind: "invalid" }
  | { readonly kind: "amount"; readonly minor: number };

/** The amount field as typed: empty is no donation, 1,00 € to 10.000,00 €. */
export function parseDonationInput(text: string): DonationInput {
  if (!text.trim()) return { kind: "empty" };
  const minor = parseAmountMinor(text);
  return minor !== null &&
    minor >= DONATION_MIN_MINOR &&
    minor <= DONATION_MAX_MINOR
    ? { kind: "amount", minor }
    : { kind: "invalid" };
}

/** The part of a create request that carries the donation, if any. */
export function donationRequestPart(input: DonationInput) {
  return input.kind === "amount" ? { donationAmountMinor: input.minor } : {};
}

export const donationStateLabels: Readonly<
  Record<NonNullable<CommitmentDonationResponse["status"]>, string>
> = {
  cancelled: "Storniert",
  paid: "Bezahlt",
  pledged: "Offen",
};

/** The order's own donation while it can still be cancelled with the order. */
export function donationToCancel(record: CommitmentRecordResponse) {
  const donation = record.donation;
  return donation?.status === "pledged" && donation.number
    ? { number: donation.number, pledgedMinor: donation.pledgedMinor }
    : null;
}

/** The order's paid donation: a cancellation of the order leaves it alone. */
export function paidDonation(record: CommitmentRecordResponse) {
  const donation = record.donation;
  return donation?.status === "paid" && donation.number
    ? { number: donation.number }
    : null;
}

/** "25,00 € · SP-2026-0007 · Offen", or the amount a draft only keeps. */
export function OrderDonation({
  record,
}: {
  readonly record: CommitmentRecordResponse;
}) {
  const { commitment, donation } = record;
  if (!donation) return null;
  const amount = euro(donation.pledgedMinor, commitment.currency);
  return (
    <span data-testid="order-donation">
      <span className="num">Spende: {amount}</span>
      {donation.donationId && donation.number ? (
        <>
          {" · "}
          <a
            className="commitment-link mono"
            data-testid="order-donation-link"
            href={donationHref(commitment.actionId, donation.donationId)}
          >
            {donation.number}
          </a>
          {donation.status ? ` · ${donationStateLabels[donation.status]}` : ""}
        </>
      ) : commitment.status === "cancelled" ? (
        <span className="subtle"> (nicht angelegt, Bestellung storniert)</span>
      ) : (
        <span className="subtle">
          {" "}
          (wird mit dem Abschluss der Bestellung angelegt)
        </span>
      )}
    </span>
  );
}
