import { useMutation } from "@tanstack/react-query";
import {
  Ban,
  Download,
  FileText,
  Mail,
  Send,
  Undo2,
  Wallet,
} from "lucide-react";
import { useState } from "react";

import type {
  DonationDeliveryResponse,
  DonationResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Button,
  buttonClassName,
  DetailProps,
  DetailSection,
  Icon,
  NextStep,
  StatusLabel,
} from "@leonaid/ui";
import { ADMIN_BASE } from "@leonaid/ui/base-paths";

import {
  documentPreviewHref,
  useDocumentDownload,
  WrapEmail,
} from "../invoices/invoice-detail";
import {
  formatDate,
  formatDateTime,
  formatFileSize,
  formatMoney,
  shortDate,
} from "../invoices/invoice-format";
import { commandKey, forgetCommandKey } from "../invoices/invoice-model";
import {
  donationCommandStorageKey,
  donationErrorMessage,
  donationSourceLabels,
  donationStatusLabels,
  type DonationRow,
  withPeriod,
} from "./donation-model";

export type DonationCommand = "payment" | "withdrawal" | "cancellation";

export interface DonationDetailProps {
  readonly row: DonationRow;
  readonly client: LeonAidApiClient;
  /** Server right `mayManage`: payments, withdrawals, cancellation. */
  readonly mayManage: boolean;
  /** Server right `maySend`: send, resend and retry the pledge mail. */
  readonly maySend: boolean;
  readonly onCommand: (command: DonationCommand, row: DonationRow) => void;
  readonly onChanged: () => void;
  readonly today: string;
}

const FINANCE_ROLE = "Berechtigte Finanzrolle";

const deliveryStatus = {
  failed: {
    label: "Versand fehlgeschlagen",
    description:
      "Die E-Mail wurde nicht zugestellt. Die Spendenzusage bleibt unverändert und kann kontrolliert erneut gesendet werden.",
  },
  queued: {
    label: "Für Versand eingeplant",
    description:
      "Der Versandauftrag ist gespeichert und wird vom Hintergrunddienst übernommen.",
  },
  retrying: {
    label: "Automatischer Neuversuch",
    description:
      "Der letzte Versuch ist fehlgeschlagen. LeonAid versucht die Zustellung erneut.",
  },
  sending: {
    label: "Wird gerade versendet",
    description:
      "Das gespeicherte PDF der Spendenzusage wird jetzt an den Spender übertragen.",
  },
  sent: {
    label: "Erfolgreich versendet",
    description:
      "Der Mailserver hat die Nachricht mit genau dieser PDF-Version angenommen.",
  },
} as const;

/** The pane body of one donation: stamps, explicit commands and the record. */
export function DonationDetail({
  client,
  mayManage,
  maySend,
  onChanged,
  onCommand,
  row,
  today,
}: DonationDetailProps) {
  const { donation } = row;
  const { cancellation, donor, payment } = donation;
  const money = (minor: number) => formatMoney(minor, donation.currency);
  const latest = donation.pledgeDeliveries[0];

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

      {maySend && latest?.status === "failed" ? (
        <FailedPledgeDelivery
          client={client}
          delivery={latest}
          donation={donation}
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
            <PledgeDocument client={client} donation={donation} />
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
              {mayManage ? (
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

      <PledgeDelivery
        client={client}
        donation={donation}
        maySend={maySend}
        onChanged={onChanged}
      />
    </div>
  );
}

/** The pledge PDF in its state: missing, being rendered, removed or ready. */
function PledgeDocument({
  client,
  donation,
}: {
  readonly client: LeonAidApiClient;
  readonly donation: DonationResponse;
}) {
  const generated = donation.pledgeDocument;
  if (!generated) {
    return (
      <p
        className="small muted"
        data-state="missing"
        data-testid="donation-pledge-document"
      >
        Das PDF der Spendenzusage ist noch nicht angelegt. Der Dokumentauftrag
        muss geprüft werden.
      </p>
    );
  }
  if (generated.status === "pending") {
    return (
      <p
        aria-live="polite"
        className="small muted"
        data-state="pending"
        data-testid="donation-pledge-document"
      >
        Das PDF der Spendenzusage wird erzeugt und danach unveränderlich
        gespeichert.
      </p>
    );
  }
  if (generated.status === "deleted") {
    return (
      <p
        className="small muted"
        data-state="deleted"
        data-testid="donation-pledge-document"
      >
        {generated.filename ?? "Das PDF"} wurde kontrolliert entfernt.
      </p>
    );
  }
  return (
    <AvailablePledgeDocument
      actionId={donation.actionId}
      client={client}
      documentId={generated.id}
      filename={generated.filename ?? `Spendenzusage-${donation.number}.pdf`}
      sizeBytes={generated.sizeBytes}
    />
  );
}

function AvailablePledgeDocument({
  actionId,
  client,
  documentId,
  filename,
  sizeBytes,
}: {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  readonly documentId: string;
  readonly filename: string;
  readonly sizeBytes: number | null;
}) {
  const { busy, download, errorMessage } = useDocumentDownload(
    client,
    actionId,
    documentId,
    filename,
  );
  return (
    <ul
      aria-busy={busy || undefined}
      className="doc-list"
      data-state="available"
      data-testid="donation-pledge-document"
    >
      <li>
        <Icon icon={FileText} size={16} />
        <span className="grow">
          {filename}
          <span className="subtle small">
            {" "}
            · PDF{sizeBytes != null ? ` · ${formatFileSize(sizeBytes)}` : ""}
          </span>
        </span>
        <a
          aria-label={`${filename} im Browser öffnen`}
          className={buttonClassName({ size: "sm", variant: "ghost" })}
          data-testid="preview-donation-pledge"
          href={documentPreviewHref(actionId, documentId)}
          rel="noopener noreferrer"
          target="_blank"
        >
          <Icon icon={FileText} size={16} />
          <span className="btn-label">Öffnen</span>
        </a>
        <Button
          aria-label={`${filename} herunterladen`}
          data-testid="download-donation-pledge"
          icon={Download}
          loading={busy}
          onClick={() => void download()}
          size="sm"
          variant="ghost"
        >
          PDF
        </Button>
      </li>
      {errorMessage ? (
        <li className="inv-error" role="alert">
          {errorMessage}
        </li>
      ) : null}
    </ul>
  );
}

/** A failed pledge mail with the explicit retry command. */
function FailedPledgeDelivery({
  client,
  delivery,
  donation,
  onChanged,
}: {
  readonly client: LeonAidApiClient;
  readonly delivery: DonationDeliveryResponse;
  readonly donation: DonationResponse;
  readonly onChanged: () => void;
}) {
  const [errorMessage, setErrorMessage] = useState<string>();
  const storageKey = donationCommandStorageKey(
    "pledge-delivery-retry",
    delivery.id,
  );
  const retry = useMutation({
    mutationFn: () =>
      client.retryDonationPledgeDelivery(
        donation.actionId,
        donation.id,
        delivery.id,
        {
          headers: {
            "Idempotency-Key": commandKey(
              storageKey,
              "donation:pledge-delivery-retry",
            ),
          },
        },
      ),
    onError(cause) {
      const message = donationErrorMessage(cause);
      setErrorMessage(message.message);
      if (message.conflict) onChanged();
    },
    onSuccess() {
      forgetCommandKey(storageKey);
      setErrorMessage(undefined);
      onChanged();
    },
  });
  return (
    <div
      className="callout tone-danger inv-callout"
      data-testid="donation-pledge-delivery-failed"
      role="status"
    >
      <Icon icon={Mail} size={16} />
      <span className="grow">
        Versand der Spendenzusage an {delivery.recipientEmail} fehlgeschlagen
        {delivery.lastErrorDetail ? `: ${delivery.lastErrorDetail}` : ""}.{" "}
        {delivery.canRetry
          ? "Prüfen Sie die Adresse und senden Sie erneut."
          : "Ein erneuter Versand ist für diesen Auftrag nicht möglich."}
        {errorMessage ? (
          <span className="inv-callout-error" role="alert">
            {errorMessage}
          </span>
        ) : null}
      </span>
      {delivery.canRetry ? (
        <Button
          data-testid="retry-donation-pledge-delivery"
          icon={Send}
          loading={retry.isPending}
          onClick={() => retry.mutate()}
          size="sm"
        >
          Erneut senden
        </Button>
      ) : null}
    </div>
  );
}

/** The e-mail delivery of the pledge: state, log and the send commands. */
function PledgeDelivery({
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
  const [errorMessage, setErrorMessage] = useState<string>();
  const [confirmResend, setConfirmResend] = useState(false);
  const deliveries = donation.pledgeDeliveries;
  const latest = deliveries[0];
  const donorEmail = donation.donor.email;
  const documentAvailable = donation.pledgeDocument?.status === "available";
  const cancelled = donation.status === "cancelled";
  const storageKey = donationCommandStorageKey("pledge-delivery", donation.id);
  const send = useMutation({
    mutationFn: () =>
      client.sendDonationPledge(donation.actionId, donation.id, {
        headers: {
          "Idempotency-Key": commandKey(storageKey, "donation:pledge-delivery"),
        },
      }),
    onError(cause) {
      const message = donationErrorMessage(cause);
      setErrorMessage(message.message);
      if (message.conflict) onChanged();
    },
    onSuccess() {
      forgetCommandKey(storageKey);
      setConfirmResend(false);
      setErrorMessage(undefined);
      onChanged();
    },
  });
  const status = latest ? deliveryStatus[latest.status] : undefined;
  // A new mail goes to the donor's stored address.
  const canSend = maySend && !cancelled && documentAvailable && donorEmail;

  return (
    <section
      aria-busy={send.isPending}
      className="pane-section"
      data-state={latest?.status ?? "not-sent"}
      data-testid="donation-pledge-delivery"
    >
      <h3>Versand der Spendenzusage</h3>
      <DetailProps
        items={[
          { label: "Status", value: status?.label ?? "Noch nicht versendet" },
          {
            label: "Empfänger",
            value: donorEmail ? (
              <WrapEmail value={donorEmail} />
            ) : (
              "Keine E-Mail-Adresse hinterlegt"
            ),
          },
        ]}
      />
      <p className="small subtle inv-note">
        {status?.description ??
          "Das unveränderliche PDF der Spendenzusage geht direkt an die E-Mail-Adresse des Spenders."}
      </p>

      {deliveries.length ? (
        <ol aria-label="Versandprotokoll" className="timeline inv-attempts">
          {deliveries.map((delivery, index) => (
            <li
              data-status={delivery.status}
              data-testid="donation-pledge-delivery-attempt"
              key={delivery.id}
            >
              <span>
                <strong>
                  {index === 0 ? "Aktueller Versand" : "Früherer Versand"}
                </strong>{" "}
                · {deliveryStatus[delivery.status].label}
                <span className="inv-attempt-subject">
                  {delivery.subject} · an {delivery.recipientEmail}
                </span>
                {delivery.lastErrorDetail ? (
                  <span className="inv-attempt-error">
                    <strong>Letzter Fehler:</strong> {delivery.lastErrorDetail}
                    {delivery.lastErrorCode
                      ? ` (${delivery.lastErrorCode})`
                      : ""}
                  </span>
                ) : null}
                <time dateTime={delivery.sentAt ?? delivery.requestedAt}>
                  {delivery.sentAt
                    ? `Versendet ${formatDateTime(delivery.sentAt)}`
                    : `Angelegt ${formatDateTime(delivery.requestedAt)}`}{" "}
                  · {delivery.attempts}{" "}
                  {delivery.attempts === 1 ? "Versuch" : "Versuche"}
                </time>
              </span>
            </li>
          ))}
        </ol>
      ) : null}

      {canSend && !latest ? (
        <div className="cluster inv-section-actions">
          <Button
            data-testid="send-donation-pledge"
            icon={Send}
            loading={send.isPending}
            onClick={() => send.mutate()}
            size="sm"
            variant="secondary"
          >
            Spendenzusage senden
          </Button>
        </div>
      ) : null}

      {canSend && latest?.status === "sent" && !confirmResend ? (
        <div className="cluster inv-section-actions">
          <Button
            data-testid="resend-donation-pledge"
            icon={Send}
            onClick={() => setConfirmResend(true)}
            size="sm"
            variant="secondary"
          >
            Erneut senden
          </Button>
        </div>
      ) : null}

      {confirmResend ? (
        <div
          aria-label="Erneut senden bestätigen"
          className="callout inv-confirm"
          role="group"
        >
          <div className="stack">
            <p>
              Es geht eine zweite E-Mail mit derselben PDF-Version an{" "}
              <strong>{donorEmail}</strong>.
            </p>
            <div className="cluster">
              <Button
                disabled={send.isPending}
                onClick={() => setConfirmResend(false)}
                size="sm"
                variant="ghost"
              >
                Abbrechen
              </Button>
              <Button
                data-testid="confirm-resend-donation-pledge"
                icon={Send}
                loading={send.isPending}
                onClick={() => send.mutate()}
                size="sm"
                variant="primary"
              >
                Erneut senden
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {maySend && !cancelled && donorEmail && !latest && !documentAvailable ? (
        <p className="small muted inv-note">
          Der Versand ist möglich, sobald das PDF der Spendenzusage bereitsteht.
        </p>
      ) : null}
      {!cancelled && !donorEmail ? (
        <p
          className="small muted inv-note"
          data-testid="donation-donor-email-missing"
        >
          Für den Versand fehlt die E-Mail-Adresse des Spenders. Senden Sie die
          Spendenzusage auf anderem Weg, zum Beispiel als ausgedrucktes PDF.
        </p>
      ) : null}
      {errorMessage ? (
        <p className="small inv-error" role="alert">
          {errorMessage}
        </p>
      ) : null}
    </section>
  );
}
