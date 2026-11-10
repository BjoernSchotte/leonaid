import { Ban, FileCheck, Undo2, Wallet } from "lucide-react";

import type {
  DonationListResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Button,
  DetailProps,
  DetailSection,
  NextStep,
  StatusLabel,
} from "@leonaid/ui";
import { ADMIN_BASE } from "@leonaid/ui/base-paths";

import { WrapEmail } from "../invoices/invoice-detail";
import {
  formatDate,
  formatDateTime,
  formatMoney,
  shortDate,
} from "../invoices/invoice-format";
import {
  DonationDelivery,
  DonationDocument,
  FailedDonationDelivery,
  PLEDGE,
  RECEIPT,
} from "./donation-delivery";
import {
  donationCommandStorageKey,
  FINANCE_ROLE,
  donationReceiptNoticeExpired,
  donationSourceLabels,
  donationStatusLabels,
  type DonationRow,
  RECEIPT_BLOCKS_WITHDRAWAL,
  validDonationReceipt,
  withPeriod,
} from "./donation-model";
import {
  DonationReceiptDelivery,
  DonationReceiptSection,
} from "./donation-receipt";

export type DonationCommand =
  | "payment"
  | "withdrawal"
  | "cancellation"
  | "receipt"
  | "receipt-void";

export interface DonationDetailProps {
  readonly row: DonationRow;
  readonly client: LeonAidApiClient;
  /** Server right `mayManage`: payments, withdrawals, cancellation, receipts. */
  readonly mayManage: boolean;
  /** Server right `maySend`: send, resend and retry the pledge and receipt mails. */
  readonly maySend: boolean;
  /** How the receiving body signs a receipt; null without a receiving body. */
  readonly receiptSigning: DonationListResponse["receiptSigning"];
  /** Last day the receiving body's notice carries a receipt (ISO day). */
  readonly receiptNoticeValidUntil: string | null;
  readonly onCommand: (command: DonationCommand, row: DonationRow) => void;
  readonly onChanged: () => void;
  readonly today: string;
}

/** The pane body of one donation: stamps, explicit commands and the record. */
export function DonationDetail({
  client,
  mayManage,
  maySend,
  onChanged,
  onCommand,
  receiptNoticeValidUntil,
  receiptSigning,
  row,
  today,
}: DonationDetailProps) {
  const { donation } = row;
  const { cancellation, donor, payment } = donation;
  const money = (minor: number) => formatMoney(minor, donation.currency);
  const latest = donation.pledgeDeliveries[0];
  const receipt = validDonationReceipt(donation);
  const latestReceiptMail = receipt?.deliveries[0];
  const noticeExpired = donationReceiptNoticeExpired(
    receiptNoticeValidUntil,
    today,
  );
  // A receipt needs the payment, a receiving body and a notice that still
  // carries it. The server checks all three again.
  const mayIssueReceipt =
    mayManage &&
    donation.status === "paid" &&
    !receipt &&
    receiptSigning !== null &&
    !noticeExpired;

  return (
    <div
      className="inv-detail"
      data-donation-id={donation.id}
      data-status={donation.status}
      data-testid="donation-detail"
    >
      {cancellation ? (
        <div className="inv-stamp-row" data-testid="donation-stamp">
          <span className="stamp">Storniert</span>
          <span className="small muted">
            Grund: {cancellation.reason.replace(/[.!?]\s*$/, "")}. Die Spende
            bleibt unverändert erhalten.
          </span>
        </div>
      ) : payment ? (
        <div className="inv-stamp-row" data-testid="donation-stamp">
          <span className="stamp tone-ok">Bezahlt</span>
          <span className="small muted">
            {withPeriod(
              `${money(payment.amountMinor)} eingegangen am ${shortDate(payment.receivedOn, today)}`,
            )}
            {receipt ? ` Bestätigt mit ${receipt.number}.` : ""}
          </span>
        </div>
      ) : null}

      {mayManage && donation.status === "pledged" ? (
        <NextStep
          action={
            <Button
              data-testid="open-donation-payment-form"
              icon={Wallet}
              onClick={() => onCommand("payment", row)}
              variant="primary"
            >
              Zahlung erfassen
            </Button>
          }
          alternatives={
            <Button
              data-testid="open-donation-cancellation-form"
              icon={Ban}
              onClick={() => onCommand("cancellation", row)}
              variant="ghost"
            >
              Spende stornieren
            </Button>
          }
          consequence="Erfassen Sie den Zahlungseingang, sobald das Geld auf dem Spendenkonto ist."
          lead={withPeriod(
            `Zugesagt am ${shortDate(donation.pledgedAt, today)}`,
          )}
        />
      ) : null}

      {mayIssueReceipt && payment ? (
        <NextStep
          action={
            <Button
              data-testid="open-donation-receipt-form"
              icon={FileCheck}
              onClick={() => onCommand("receipt", row)}
              variant="primary"
            >
              Zuwendungsbestätigung ausstellen
            </Button>
          }
          consequence="Die Zuwendungsbestätigung bestätigt den eingegangenen Betrag und den Tag des Eingangs. Sie kann danach nicht mehr geändert werden."
          lead={withPeriod(
            `${money(payment.amountMinor)} eingegangen am ${shortDate(payment.receivedOn, today)}`,
          )}
        />
      ) : null}

      {maySend && latest?.status === "failed" ? (
        <FailedDonationDelivery
          client={client}
          delivery={latest}
          donation={donation}
          kind={PLEDGE}
          onChanged={onChanged}
        />
      ) : null}
      {maySend && latestReceiptMail?.status === "failed" ? (
        <FailedDonationDelivery
          client={client}
          delivery={latestReceiptMail}
          donation={donation}
          kind={RECEIPT}
          onChanged={onChanged}
        />
      ) : null}

      <DetailSection title="Spende">
        <div data-testid="donation-summary">
          <DetailProps
            items={[
              {
                label: "Nummer",
                value: <span className="mono">{donation.number}</span>,
              },
              {
                label: "Status",
                value: (
                  <StatusLabel status={donationStatusLabels[donation.status]} />
                ),
              },
              {
                label: "Zugesagt",
                value: (
                  <span className="num" data-testid="donation-pledged-amount">
                    {money(donation.pledgedMinor)}
                  </span>
                ),
              },
              ...(payment
                ? [
                    {
                      label: "Eingegangen",
                      value: (
                        <span
                          className="num"
                          data-testid="donation-received-amount"
                        >
                          {money(payment.amountMinor)}
                        </span>
                      ),
                    },
                  ]
                : []),
              {
                label: "Zugesagt am",
                value: formatDateTime(donation.pledgedAt),
              },
              {
                label: "Herkunft",
                value: (
                  <span data-testid="donation-source">
                    {donationSourceLabels[donation.source]}
                  </span>
                ),
              },
              ...(donation.createdByDisplayName
                ? [
                    {
                      label: "Erfasst von",
                      value: donation.createdByDisplayName,
                    },
                  ]
                : []),
              ...(donation.note
                ? [{ label: "Notiz", value: donation.note }]
                : []),
              ...(donation.commitmentId
                ? [
                    {
                      label: "Bestellung",
                      value: (
                        <a
                          data-testid="donation-order-link"
                          href={`${ADMIN_BASE}orders?action=${encodeURIComponent(donation.actionId)}&open=${encodeURIComponent(donation.commitmentId)}`}
                        >
                          Bestellung öffnen
                        </a>
                      ),
                    },
                  ]
                : []),
            ]}
          />
        </div>
      </DetailSection>

      <DetailSection title="Spender">
        <div data-testid="donation-donor">
          <DetailProps
            items={[
              { label: "Name", value: donor.name },
              {
                label: "Adresse",
                value: `${donor.streetLine1}, ${donor.postalCode} ${donor.city}, ${donor.countryCode}`,
              },
              {
                label: "E-Mail",
                value: donor.email ? <WrapEmail value={donor.email} /> : "–",
              },
            ]}
          />
        </div>
      </DetailSection>

      <DetailSection title="Spendenzusage">
        <div data-testid="donation-pledge">
          <DetailProps
            items={[
              {
                label: "Nummer",
                value: <span className="mono">{donation.number}</span>,
              },
              { label: "Datum", value: formatDate(donation.pledgedAt) },
            ]}
          />
          <div className="inv-note">
            {/* Every donation has its pledge document from the moment it
                is recorded. */}
            <DonationDocument
              actionId={donation.actionId}
              client={client}
              document={donation.pledgeDocument}
              fallbackFilename={`Spendenzusage-${donation.number}.pdf`}
              kind={PLEDGE}
            />
          </div>
        </div>
      </DetailSection>

      <DetailSection title="Zahlung">
        <div data-testid="donation-payment">
          {payment ? (
            <>
              <DetailProps
                items={[
                  {
                    label: "Eingegangen",
                    value: (
                      <span className="num">
                        {money(payment.amountMinor)}
                        {payment.amountMinor !== donation.pledgedMinor
                          ? ` (${money(Math.abs(payment.amountMinor - donation.pledgedMinor))} ${payment.amountMinor > donation.pledgedMinor ? "mehr" : "weniger"} als zugesagt)`
                          : ""}
                      </span>
                    ),
                  },
                  {
                    label: "Eingangsdatum",
                    value: formatDate(payment.receivedOn),
                  },
                  ...(payment.note
                    ? [{ label: "Notiz", value: payment.note }]
                    : []),
                  {
                    label: "Erfasst",
                    value: `${payment.recordedByDisplayName ?? FINANCE_ROLE}, ${formatDateTime(payment.recordedAt)}`,
                  },
                ]}
              />
              {mayManage && receipt ? (
                <p
                  className="small subtle inv-note"
                  data-testid="donation-receipt-blocks-withdrawal"
                >
                  {RECEIPT_BLOCKS_WITHDRAWAL}
                </p>
              ) : mayManage ? (
                <div className="cluster inv-section-actions">
                  <Button
                    data-testid="open-donation-withdrawal-form"
                    icon={Undo2}
                    onClick={() => onCommand("withdrawal", row)}
                    size="sm"
                    variant="ghost"
                  >
                    Zahlung zurücknehmen
                  </Button>
                </div>
              ) : null}
              <p
                className="small subtle inv-note"
                data-testid="donation-paid-no-cancel"
              >
                Eine bezahlte Spende kann nicht storniert werden. Wurde die
                Zahlung irrtümlich erfasst, wird sie zuerst zurückgenommen.
              </p>
            </>
          ) : (
            <p className="small muted">
              {cancellation
                ? "Für diese Spende ist keine Zahlung erfasst."
                : "Noch keine Zahlung erfasst."}
            </p>
          )}
          {donation.paymentWithdrawals.length ? (
            <>
              <h4 className="small inv-note">Zurückgenommene Zahlungen</h4>
              <ul className="inv-payments">
                {donation.paymentWithdrawals.map((withdrawal) => (
                  <li
                    className="is-reversed"
                    data-testid="donation-payment-withdrawal"
                    key={withdrawal.id}
                  >
                    <div className="inv-payment-head">
                      <span className="num is-struck">
                        {money(withdrawal.amountMinor)}
                      </span>
                      <span className="grow small muted">
                        eingegangen am {formatDate(withdrawal.receivedOn)}
                      </span>
                    </div>
                    <DetailProps
                      items={[
                        ...(withdrawal.note
                          ? [{ label: "Notiz", value: withdrawal.note }]
                          : []),
                        {
                          label: "Erfasst",
                          value: `${withdrawal.recordedByDisplayName ?? FINANCE_ROLE}, ${formatDateTime(withdrawal.recordedAt)}`,
                        },
                        {
                          label: "Zurückgenommen",
                          value: `${withdrawal.withdrawnByDisplayName ?? FINANCE_ROLE}, ${formatDateTime(withdrawal.withdrawnAt)}: ${withdrawal.reason}`,
                        },
                      ]}
                    />
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </div>
      </DetailSection>

      <DonationReceiptSection
        client={client}
        donation={donation}
        mayManage={mayManage}
        noticeExpiredOn={noticeExpired ? receiptNoticeValidUntil : null}
        onVoid={() => onCommand("receipt-void", row)}
      />

      {cancellation ? (
        <DetailSection title="Storno">
          <div data-testid="donation-cancellation">
            <DetailProps
              items={[
                { label: "Grund", value: cancellation.reason },
                {
                  label: "Storniert",
                  value: `${cancellation.cancelledByDisplayName ?? "Berechtigte Rolle"}, ${formatDateTime(cancellation.cancelledAt)}`,
                },
              ]}
            />
          </div>
        </DetailSection>
      ) : null}

      <DonationDelivery
        // A pledge asks for a payment: only an open donation sends it.
        blocked={donation.status !== "pledged"}
        deliveries={donation.pledgeDeliveries}
        documentAvailable={donation.pledgeDocument.status === "available"}
        donorEmail={donor.email}
        idempotencyPrefix="donation:pledge-delivery"
        kind={PLEDGE}
        maySend={maySend}
        onChanged={onChanged}
        send={(options) =>
          client.sendDonationPledge(donation.actionId, donation.id, options)
        }
        storageKey={donationCommandStorageKey("pledge-delivery", donation.id)}
      />
      <DonationReceiptDelivery
        client={client}
        donation={donation}
        maySend={maySend}
        onChanged={onChanged}
      />
    </div>
  );
}
