import { Ban, TriangleAlert } from "lucide-react";

import type {
  DonationReceiptResponse,
  DonationResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, DetailProps, DetailSection, Icon } from "@leonaid/ui";
import { adminHref } from "@leonaid/ui/base-paths";

import {
  formatDate,
  formatDateTime,
  formatMoney,
} from "../invoices/invoice-format";
import {
  DonationDelivery,
  DonationDocument,
  RECEIPT,
  VOID_RECEIPT,
} from "./donation-delivery";
import {
  donationCommandStorageKey,
  FINANCE_ROLE,
  donationReceiptEvidenceLabels,
  validDonationReceipt,
} from "./donation-model";

const receiptFilename = (receipt: DonationReceiptResponse) =>
  `Zuwendungsbestaetigung-${receipt.number}.pdf`;

/**
 * "Zuwendungsbestätigung": the valid receipt of a paid donation with its
 * PDF, or why there is none yet, and below it the voided receipts. The
 * command to issue one is the pane's next step, not part of this section.
 */
export function DonationReceiptSection({
  client,
  donation,
  mayManage,
  noticeExpiredOn,
  onVoid,
}: {
  readonly client: LeonAidApiClient;
  readonly donation: DonationResponse;
  /** Server right `mayManage`: issue and void. */
  readonly mayManage: boolean;
  /**
   * The last day the receiving body's notice carried a receipt, when that
   * day has passed (§ 63 Abs. 5 AO); null while a receipt can be issued.
   */
  readonly noticeExpiredOn: string | null;
  readonly onVoid: () => void;
}) {
  const receipt = validDonationReceipt(donation);
  const voided = donation.receipts.filter((item) => item.void !== null);
  const money = (minor: number) => formatMoney(minor, donation.currency);
  // A cancelled donation gets no receipt; it only shows what it once had.
  if (donation.status === "cancelled" && donation.receipts.length === 0) {
    return null;
  }

  return (
    <DetailSection title="Zuwendungsbestätigung">
      <div
        data-state={receipt ? "issued" : "none"}
        data-testid="donation-receipt"
      >
        {receipt ? (
          <>
            <DetailProps
              items={[
                {
                  label: "Nummer",
                  value: (
                    <span
                      className="mono"
                      data-testid="donation-receipt-number"
                    >
                      {receipt.number}
                    </span>
                  ),
                },
                { label: "Datum", value: formatDate(receipt.issuedOn) },
                {
                  label: "Bestätigt",
                  value: (
                    <span className="num">
                      {money(receipt.amountMinor)}, eingegangen am{" "}
                      {formatDate(receipt.receivedOn)}
                    </span>
                  ),
                },
                {
                  label: "Ausgestellt",
                  value: `${receipt.issuedByDisplayName ?? FINANCE_ROLE}, ${formatDateTime(receipt.issuedAt)}`,
                },
              ]}
            />
            <div className="inv-note">
              <DonationDocument
                actionId={donation.actionId}
                client={client}
                document={receipt.document}
                fallbackFilename={receiptFilename(receipt)}
                kind={RECEIPT}
              />
            </div>
            {receipt.signing === "by_hand" ? (
              <p
                className="small subtle inv-note"
                data-testid="donation-receipt-by-hand"
              >
                Ausdrucken und unterschreiben. Diese Zuwendungsbestätigung gilt
                nur mit Unterschrift und wird nicht per E-Mail gesendet.
              </p>
            ) : null}
            {mayManage ? (
              <div className="cluster inv-section-actions">
                <Button
                  data-testid="open-donation-receipt-void-form"
                  icon={Ban}
                  onClick={onVoid}
                  size="sm"
                  variant="ghost"
                >
                  Für ungültig erklären
                </Button>
              </div>
            ) : null}
          </>
        ) : donation.status === "cancelled" ? null : donation.status ===
          "pledged" ? (
          <p className="small muted">
            Eine Zuwendungsbestätigung gibt es nach dem Zahlungseingang.
          </p>
        ) : mayManage && noticeExpiredOn !== null ? (
          <div
            className="callout tone-warn inv-callout"
            data-testid="donation-receipt-notice-expired"
            role="status"
          >
            <Icon icon={TriangleAlert} size={16} />
            <span className="grow">
              Der Bescheid der empfangenden Körperschaft trägt
              Zuwendungsbestätigungen nur bis zum {formatDate(noticeExpiredOn)}{" "}
              (§ 63 Abs. 5 AO). Tragen Sie unter „Rechtliches“ im Teil „Spenden“
              den neuen Bescheid ein.{" "}
              <a href={adminHref("legal/donations")}>Zu „Rechtliches“</a>
            </span>
          </div>
        ) : (
          <p className="small muted">
            Noch keine Zuwendungsbestätigung ausgestellt.
          </p>
        )}

        {voided.length ? (
          <>
            <h4 className="small inv-note">
              Ungültige Zuwendungsbestätigungen
            </h4>
            <ul
              className="inv-payments"
              data-testid="donation-receipt-void-list"
            >
              {voided.map((item) => (
                <VoidReceipt
                  client={client}
                  donation={donation}
                  key={item.id}
                  receipt={item}
                />
              ))}
            </ul>
          </>
        ) : null}
      </div>
    </DetailSection>
  );
}

/** One voided receipt: what it confirmed, why it is void, its stored PDF. */
function VoidReceipt({
  client,
  donation,
  receipt,
}: {
  readonly client: LeonAidApiClient;
  readonly donation: DonationResponse;
  readonly receipt: DonationReceiptResponse;
}) {
  const voided = receipt.void;
  if (!voided) return null;
  const sent = receipt.deliveries.find((delivery) => delivery.sentAt !== null);
  return (
    <li className="is-reversed" data-testid="donation-receipt-void">
      <div className="inv-payment-head">
        <span className="mono is-struck">{receipt.number}</span>
        <span className="grow small muted">
          vom {formatDate(receipt.issuedOn)} ·{" "}
          {formatMoney(receipt.amountMinor, donation.currency)}, eingegangen am{" "}
          {formatDate(receipt.receivedOn)}
        </span>
      </div>
      <DetailProps
        items={[
          { label: "Grund", value: voided.reason },
          {
            label: "Original",
            value: donationReceiptEvidenceLabels[voided.evidence],
          },
          {
            label: "Ausgestellt",
            value: `${receipt.issuedByDisplayName ?? FINANCE_ROLE}, ${formatDateTime(receipt.issuedAt)}`,
          },
          ...(sent?.sentAt
            ? [
                {
                  label: "Gesendet",
                  value: `an ${sent.recipientEmail}, ${formatDateTime(sent.sentAt)}`,
                },
              ]
            : []),
          {
            label: "Für ungültig erklärt",
            value: `${voided.voidedByDisplayName ?? FINANCE_ROLE}, ${formatDateTime(voided.voidedAt)}`,
          },
        ]}
      />
      <div className="inv-note">
        <DonationDocument
          actionId={donation.actionId}
          client={client}
          document={receipt.document}
          fallbackFilename={receiptFilename(receipt)}
          kind={VOID_RECEIPT}
        />
      </div>
    </li>
  );
}

/**
 * The e-mail delivery of the valid receipt. Only a receipt that is valid
 * without a signature ("machine") can be sent; one signed by hand has no
 * delivery at all.
 */
export function DonationReceiptDelivery({
  client,
  donation,
  maySend,
  onChanged,
}: {
  readonly client: LeonAidApiClient;
  readonly donation: DonationResponse;
  readonly maySend: boolean;
  readonly onChanged: () => void;
}) {
  const receipt = validDonationReceipt(donation);
  if (!receipt || receipt.signing !== "machine") return null;
  return (
    <DonationDelivery
      blocked={false}
      deliveries={receipt.deliveries}
      documentAvailable={receipt.document.status === "available"}
      donorEmail={donation.donor.email}
      idempotencyPrefix="donation:receipt-delivery"
      // A new receipt is a new document: its own state and its own key.
      key={receipt.id}
      kind={RECEIPT}
      maySend={maySend}
      onChanged={onChanged}
      send={(options) =>
        client.sendDonationReceipt(
          donation.actionId,
          donation.id,
          receipt.id,
          options,
        )
      }
      storageKey={donationCommandStorageKey("receipt-delivery", receipt.id)}
    />
  );
}
