import { useMutation } from "@tanstack/react-query";
import {
  Ban,
  Download,
  FileText,
  HandCoins,
  Lock,
  Mail,
  Send,
  Undo2,
  Wallet,
} from "lucide-react";
import { useState } from "react";

import {
  ApiError,
  type GeneratedDocumentRecordResponse,
  type InvoiceDeliveryResponse,
  type InvoiceRecordResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Badge,
  Button,
  buttonClassName,
  cn,
  DetailProps,
  DetailSection,
  Icon,
  NextStep,
  StatusLabel,
  useOptionalToast,
} from "@leonaid/ui";

import { actionErrorMessage } from "../action-admin/errors";
import {
  formatDate,
  formatDateTime,
  formatFileSize,
  formatIban,
  formatMoney,
  relativeDay,
  shortDate,
} from "./invoice-format";
import {
  cancellationDeliveryCommandStorageKey,
  cancellationDocumentCommandStorageKey,
  commandKey,
  deliveryCommandStorageKey,
  forgetCommandKey,
  invoiceDispatchLabels,
  invoiceSettlement,
  invoiceStatusLabels,
  type InvoiceRow,
} from "./invoice-model";
import { ADMIN_BASE } from "@leonaid/ui/base-paths";

export type InvoiceCommand = "payment" | "cancellation" | "reversal" | "refund";

export interface InvoiceDetailProps {
  readonly row: InvoiceRow;
  readonly client: LeonAidApiClient;
  /**
   * Server right `mayIssue`: send, resend and retry the e-mail delivery of
   * the invoice and of its cancellation invoice.
   */
  readonly canManageDelivery: boolean;
  /**
   * Server right `mayManageSettlements`: payments, reversals, cancellation,
   * issuing a missing cancellation invoice and settling its refund.
   */
  readonly canManageSettlement: boolean;
  readonly onCommand: (
    command: InvoiceCommand,
    row: InvoiceRow,
    paymentId?: string,
  ) => void;
  readonly onChanged: () => void;
  readonly today: string;
}

/** Which document a delivery carries: the invoice or its cancellation invoice. */
type DeliveryKind = "invoice" | "cancellation";

/** The words and test ids that differ between the two delivery flows. */
const deliveryKinds = {
  invoice: {
    title: "Versand",
    testId: "invoice-delivery",
    send: "Rechnung senden",
    sendTestId: "send-invoice",
    resendTestId: "resend-invoice",
    confirmResendTestId: "confirm-resend-invoice",
    retryTestId: "retry-invoice-delivery",
    failedSubject: "Versand",
    notSent:
      "Das unveränderliche Rechnungs-PDF geht direkt an den gespeicherten Empfänger.",
    waitsForDocument:
      "Der Versand ist möglich, sobald das Rechnungs-PDF bereitsteht.",
    descriptions: {} as Partial<Record<DeliveryStatus, string>>,
  },
  cancellation: {
    title: "Versand der Stornorechnung",
    testId: "cancellation-delivery",
    send: "Stornorechnung senden",
    sendTestId: "send-cancellation",
    resendTestId: "resend-cancellation",
    confirmResendTestId: "confirm-resend-cancellation",
    retryTestId: "retry-cancellation-delivery",
    failedSubject: "Versand der Stornorechnung",
    notSent:
      "Das unveränderliche PDF der Stornorechnung geht direkt an den gespeicherten Empfänger der Rechnung.",
    waitsForDocument:
      "Der Versand ist möglich, sobald das PDF der Stornorechnung bereitsteht.",
    descriptions: {
      failed:
        "Die E-Mail wurde nicht zugestellt. Die Stornorechnung bleibt unverändert und kann kontrolliert erneut gesendet werden.",
      sending:
        "Das gespeicherte PDF der Stornorechnung wird jetzt an den Empfänger übertragen.",
    } as Partial<Record<DeliveryStatus, string>>,
  },
} as const;

type DeliveryStatus = InvoiceDeliveryResponse["status"];

const deliveryStatus = {
  failed: {
    label: "Versand fehlgeschlagen",
    description:
      "Die E-Mail wurde nicht zugestellt. Die Rechnung bleibt unverändert und kann kontrolliert erneut gesendet werden.",
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
      "Das gespeicherte Rechnungs-PDF wird jetzt an den Empfänger übertragen.",
  },
  sent: {
    label: "Erfolgreich versendet",
    description:
      "Der Mailserver hat die Nachricht mit genau dieser PDF-Version angenommen.",
  },
} as const;

/** The pane body of one invoice: stamps, explicit commands and the record. */
export function InvoiceDetail({
  canManageDelivery,
  canManageSettlement,
  client,
  onChanged,
  onCommand,
  row,
  today,
}: InvoiceDetailProps) {
  const { record } = row;
  const { invoice, cancellation } = record;
  const settlementState = invoiceSettlement(record);
  const settlement = cancellation
    ? "cancelled"
    : settlementState.status === "overpaid"
      ? "overpaid"
      : settlementState.status === "paid"
        ? "paid"
        : settlementState.status === "partially_paid"
          ? "partial"
          : "outstanding";
  const latestPayment = settlementState.active.at(-1);
  const money = (minor: number) => formatMoney(minor, invoice.currency);
  const latest = record.deliveries[0];
  const cancellationDeliveries = record.cancellationDeliveries ?? [];
  const latestCancellationDelivery = cancellationDeliveries[0];
  const recordPayment = (label: string, size?: "sm") => (
    <Button
      data-testid="open-payment-form"
      icon={Wallet}
      onClick={() => onCommand("payment", row)}
      size={size}
      variant={size ? "ghost" : "primary"}
    >
      {label}
    </Button>
  );
  const cancelInvoice = (size?: "sm") => (
    <Button
      data-testid="open-cancellation-form"
      icon={Ban}
      onClick={() => onCommand("cancellation", row)}
      size={size}
      variant="ghost"
    >
      Stornieren
    </Button>
  );

  return (
    <div
      className="inv-detail"
      data-invoice-id={invoice.id}
      data-settlement={settlement}
      data-settlement-version={settlementState.version}
      data-testid="invoice-detail"
    >
      {cancellation ? (
        <div className="inv-stamp-row" data-testid="invoice-stamp">
          <span className="stamp">Storniert</span>
          <span className="small muted">
            Grund: {cancellation.reason.replace(/[.!?]\s*$/, "")}. Die Rechnung
            bleibt unverändert erhalten.
          </span>
        </div>
      ) : settlement === "paid" && latestPayment ? (
        <div className="inv-stamp-row" data-testid="invoice-stamp">
          <span className="stamp tone-ok">Bezahlt</span>
          <span className="small muted">
            Zahlungseingang am {shortDate(latestPayment.receivedOn, today)},
            vollständig.
          </span>
        </div>
      ) : settlement === "overpaid" ? (
        <div className="inv-stamp-row" data-testid="invoice-stamp">
          <span className="stamp tone-warn">Überzahlt</span>
          <span className="small muted">
            {money(settlementState.overpaidMinor)} mehr eingegangen als
            berechnet.
          </span>
        </div>
      ) : null}

      {settlement === "overpaid" ? (
        <div
          className="callout tone-warn inv-callout"
          data-testid="invoice-overpaid"
          role="status"
        >
          <Icon icon={HandCoins} size={16} />
          <span className="grow">
            <strong>Differenz erstatten:</strong>{" "}
            {money(settlementState.overpaidMinor)} an {record.buyerDisplayName}{" "}
            zurücküberweisen. LeonAid bucht keine Erstattung; erfassen Sie die
            Rücküberweisung bei Ihrer Bank.
          </span>
        </div>
      ) : null}

      {canManageSettlement &&
      (settlement === "outstanding" || settlement === "partial") ? (
        <NextStep
          action={recordPayment("Zahlung erfassen")}
          alternatives={cancelInvoice()}
          consequence={
            settlement === "partial"
              ? `${money(settlementState.paidMinor)} von ${money(invoice.grossMinor)} eingegangen, ${money(record.openMinor)} offen. Erfassen Sie jeden weiteren Zahlungseingang.`
              : "Erfassen Sie den Zahlungseingang, auch wenn erst ein Teil da ist."
          }
          lead={
            row.status === "overdue"
              ? `Seit ${shortDate(invoice.dueOn, today)} überfällig.`
              : settlement === "partial"
                ? "Teilweise bezahlt."
                : `Fällig ${relativeDay(invoice.dueOn, today)}.`
          }
        />
      ) : null}

      {canManageSettlement &&
      (settlement === "paid" || settlement === "overpaid") ? (
        <div className="cluster">
          {recordPayment("Weitere Zahlung erfassen", "sm")}
          {cancelInvoice("sm")}
        </div>
      ) : null}

      {cancellation?.refundOpen ? (
        <div
          className="callout tone-warn inv-callout"
          data-testid="invoice-refund-open"
          role="status"
        >
          <Icon icon={HandCoins} size={16} />
          <span className="grow">
            <strong>Erstattung offen:</strong> Erhalten:{" "}
            {money(cancellation.receivedMinor ?? 0)}. Überweisen Sie den Betrag
            außerhalb von LeonAid an {record.buyerDisplayName} zurück und
            vermerken Sie es danach hier.
          </span>
          {canManageSettlement ? (
            <Button
              data-testid="open-refund-form"
              onClick={() => onCommand("refund", row)}
              size="sm"
            >
              Erstattung erledigt
            </Button>
          ) : null}
        </div>
      ) : null}

      {canManageDelivery && latest?.status === "failed" ? (
        <FailedDeliveryCallout
          client={client}
          delivery={latest}
          kind="invoice"
          onChanged={onChanged}
          record={record}
        />
      ) : null}

      {canManageDelivery && latestCancellationDelivery?.status === "failed" ? (
        <FailedDeliveryCallout
          client={client}
          delivery={latestCancellationDelivery}
          kind="cancellation"
          onChanged={onChanged}
          record={record}
        />
      ) : null}

      <DetailSection title="Rechnung">
        <DetailProps
          items={[
            {
              label: "Nummer",
              value: <span className="mono">{invoice.number}</span>,
            },
            {
              label: "Status",
              value: <StatusLabel status={invoiceStatusLabels[row.status]} />,
            },
            {
              label: "Betrag",
              value: (
                <span className="num">
                  {formatMoney(invoice.grossMinor, invoice.currency)}
                </span>
              ),
            },
            ...(invoice.taxMinor > 0
              ? [
                  {
                    label: "Netto",
                    value: (
                      <span className="num">
                        {formatMoney(invoice.netMinor, invoice.currency)}
                      </span>
                    ),
                  },
                ]
              : []),
            {
              label: "Steuer",
              value:
                invoice.taxMinor > 0 ? (
                  <span className="num">
                    {formatMoney(invoice.taxMinor, invoice.currency)}
                  </span>
                ) : (
                  invoice.taxNote
                ),
            },
            ...(settlementState.paidMinor > 0
              ? [
                  {
                    label: "Eingegangen",
                    value: (
                      <span className="num" data-testid="invoice-paid-amount">
                        {money(settlementState.paidMinor)}
                      </span>
                    ),
                  },
                ]
              : []),
            {
              label: "Offen",
              value: (
                <span className="num" data-testid="invoice-open-amount">
                  {money(record.openMinor)}
                </span>
              ),
            },
            ...(settlementState.overpaidMinor > 0
              ? [
                  {
                    label: "Überzahlt",
                    value: (
                      <span
                        className="num"
                        data-testid="invoice-overpaid-amount"
                      >
                        {money(settlementState.overpaidMinor)}
                      </span>
                    ),
                  },
                ]
              : []),
            { label: "Ausgestellt", value: shortDate(invoice.issuedAt, today) },
            { label: "Leistungsdatum", value: formatDate(invoice.serviceOn) },
            {
              label: "Fällig",
              value: dueText(invoice.dueOn, today),
            },
            {
              label: "Zahlungsreferenz",
              value: <span className="mono">{invoice.paymentReference}</span>,
            },
            { label: "Versand", value: invoiceDispatchLabels[row.dispatch] },
            {
              label: "Bestellung",
              value: (
                <a
                  href={`${ADMIN_BASE}orders?action=${encodeURIComponent(invoice.actionId)}&open=${encodeURIComponent(invoice.commitmentId)}`}
                >
                  Bestellung öffnen
                </a>
              ),
            },
          ]}
        />
        {invoice.taxMinor > 0 ? (
          <p className="small subtle inv-note">{invoice.taxNote}</p>
        ) : null}
      </DetailSection>

      <DetailSection title="Empfänger">
        <DetailProps
          items={[
            { label: "Name", value: invoice.recipient.recipientName },
            {
              label: "Adresse",
              value: `${invoice.recipient.streetLine1}, ${invoice.recipient.postalCode} ${invoice.recipient.city}, ${invoice.recipient.countryCode}`,
            },
            {
              label: "E-Mail",
              value: invoice.recipient.email ? (
                <WrapEmail value={invoice.recipient.email} />
              ) : (
                "–"
              ),
            },
          ]}
        />
        <p className="small subtle inv-snapshot">
          <Icon icon={Lock} size={12} /> Adresse zum Ausstellungszeitpunkt
          gespeichert. Spätere Änderungen am Sponsor ändern diese Rechnung
          nicht.
        </p>
      </DetailSection>

      <DetailSection title="Dokumente">
        <InvoiceDocument
          actionId={invoice.actionId}
          client={client}
          row={row}
        />
      </DetailSection>

      <DetailSection title="Positionen">
        <ul className="inv-lines">
          {invoice.lines.map((line, index) => (
            <li key={`${invoice.id}-${index}`}>
              <span className="grow">
                {line.quantity} × {line.description}
              </span>
              <span className="num">
                {formatMoney(line.grossMinor, line.currency)}
              </span>
            </li>
          ))}
        </ul>
      </DetailSection>

      {settlementState.payments.length > 0 ? (
        <DetailSection title="Zahlungen">
          <ul className="inv-payments" data-testid="payment-record">
            {settlementState.payments.map((payment) => (
              <li
                className={payment.reversal ? "is-reversed" : undefined}
                data-payment-id={payment.id}
                data-testid="payment-entry"
                key={payment.id}
              >
                <div className="inv-payment-head">
                  <span className={cn("num", payment.reversal && "is-struck")}>
                    {formatMoney(payment.amountMinor, payment.currency)}
                  </span>
                  <span className="grow small muted">
                    eingegangen am {formatDate(payment.receivedOn)}
                  </span>
                  {canManageSettlement && !payment.reversal && !cancellation ? (
                    <Button
                      data-testid="open-reversal-form"
                      icon={Undo2}
                      onClick={() => onCommand("reversal", row, payment.id)}
                      size="sm"
                      variant="ghost"
                    >
                      Zurückbuchen
                    </Button>
                  ) : null}
                </div>
                <DetailProps
                  items={[
                    { label: "Verwendungszweck", value: payment.reference },
                    ...(payment.note
                      ? [{ label: "Notiz", value: payment.note }]
                      : []),
                    {
                      label: "Erfasst",
                      value: `${payment.recordedByDisplayName ?? "Berechtigte Finanzrolle"}, ${formatDateTime(payment.recordedAt)}`,
                    },
                    ...(payment.reversal
                      ? [
                          {
                            label: "Zurückgebucht",
                            value: `${payment.reversal.reversedByDisplayName ?? "Berechtigte Finanzrolle"}, ${formatDateTime(payment.reversal.reversedAt)}: ${payment.reversal.reason}`,
                          },
                        ]
                      : []),
                  ]}
                />
              </li>
            ))}
          </ul>
        </DetailSection>
      ) : null}

      {cancellation ? (
        <DetailSection title="Storno">
          <div data-testid="invoice-cancellation">
            <DetailProps
              items={[
                { label: "Grund", value: cancellation.reason },
                {
                  label: "Storniert",
                  value: `${cancellation.requestedByDisplayName ?? "Berechtigte Rolle"}, ${formatDateTime(cancellation.requestedAt)}`,
                },
              ]}
            />
            <p className="small subtle inv-note">
              Eine Korrektur wird als neue, separat nummerierte Rechnung
              angelegt.
            </p>
          </div>
        </DetailSection>
      ) : null}

      {cancellation ? (
        <CancellationInvoice
          canManageSettlement={canManageSettlement}
          client={client}
          onChanged={onChanged}
          row={row}
        />
      ) : null}

      <InvoiceDelivery
        canManage={canManageDelivery}
        client={client}
        deliveries={record.deliveries}
        documentAvailable={row.document?.document.status === "available"}
        kind="invoice"
        onChanged={onChanged}
        record={record}
      />

      {cancellation?.number ? (
        <InvoiceDelivery
          canManage={canManageDelivery}
          client={client}
          deliveries={cancellationDeliveries}
          documentAvailable={
            row.cancellationDocument?.document.status === "available"
          }
          kind="cancellation"
          onChanged={onChanged}
          record={record}
        />
      ) : null}

      <DetailSection title="Rechnungssteller bei Ausstellung">
        <div data-testid={`invoice-payment-details-${invoice.id}`}>
          <DetailProps
            items={[
              { label: "Name", value: invoice.issuer.legalName },
              {
                label: "Adresse",
                value: `${invoice.issuer.streetLine1}, ${invoice.issuer.postalCode} ${invoice.issuer.city}`,
              },
              { label: "Steuernummer", value: invoice.issuer.taxIdentifier },
              {
                label: "Kontoinhaber",
                value: invoice.paymentDetails.accountHolder,
              },
              {
                label: "IBAN",
                value: (
                  <span className="mono">
                    {formatIban(invoice.paymentDetails.iban)}
                  </span>
                ),
              },
              ...(invoice.paymentDetails.bic
                ? [
                    {
                      label: "BIC",
                      value: (
                        <span className="mono">
                          {invoice.paymentDetails.bic}
                        </span>
                      ),
                    },
                  ]
                : []),
            ]}
          />
        </div>
      </DetailSection>
    </div>
  );
}

/**
 * The cancellation invoice of a cancelled invoice: its number, date and PDF,
 * the received money with the refund state, or the command that issues the
 * document for an invoice cancelled before LeonAid issued such documents.
 */
function CancellationInvoice({
  canManageSettlement,
  client,
  onChanged,
  row,
}: {
  readonly canManageSettlement: boolean;
  readonly client: LeonAidApiClient;
  readonly onChanged: () => void;
  readonly row: InvoiceRow;
}) {
  const { invoice, cancellation } = row.record;
  const toast = useOptionalToast();
  const [errorMessage, setErrorMessage] = useState<string>();
  const storageKey = cancellationDocumentCommandStorageKey(invoice.id);
  const issue = useMutation({
    mutationFn: () =>
      client.issueInvoiceCancellationDocument(invoice.actionId, invoice.id, {
        headers: {
          "Idempotency-Key": commandKey(
            storageKey,
            "invoice:cancellation-document",
          ),
        },
      }),
    onError(cause) {
      const message = actionErrorMessage(cause);
      setErrorMessage(message.message);
      // A refusal means the list is behind (someone else issued it).
      if (message.conflict) onChanged();
    },
    onSuccess(result) {
      forgetCommandKey(storageKey);
      setErrorMessage(undefined);
      toast?.show({
        title: result.number
          ? `Stornorechnung ${result.number} ausgestellt.`
          : "Stornorechnung ausgestellt.",
        tone: "success",
      });
      onChanged();
    },
  });
  if (!cancellation) return null;
  const receivedMinor = cancellation.receivedMinor ?? 0;
  const refundItems =
    receivedMinor > 0
      ? [
          {
            label: "Erhalten",
            value: (
              <span className="num" data-testid="cancellation-received-amount">
                {formatMoney(receivedMinor, invoice.currency)}
              </span>
            ),
          },
          {
            label: "Erstattung",
            value: (
              <span data-testid="cancellation-refund">
                {cancellation.refundOpen ? (
                  <Badge icon={HandCoins} tone="warn">
                    Erstattung offen
                  </Badge>
                ) : cancellation.refundSettledOn ? (
                  `Erstattung erledigt am ${formatDate(cancellation.refundSettledOn)} · ${cancellation.refundSettledByDisplayName ?? "Berechtigte Finanzrolle"}`
                ) : (
                  "–"
                )}
              </span>
            ),
          },
          ...(cancellation.refundNote
            ? [{ label: "Notiz", value: cancellation.refundNote }]
            : []),
        ]
      : [];

  return (
    <DetailSection title="Stornorechnung">
      <div
        aria-busy={issue.isPending || undefined}
        data-state={cancellation.number ? "issued" : "missing"}
        data-testid="cancellation-invoice"
      >
        {cancellation.number ? (
          <>
            <DetailProps
              items={[
                {
                  label: "Nummer",
                  value: <span className="mono">{cancellation.number}</span>,
                },
                ...(cancellation.issuedOn
                  ? [
                      {
                        label: "Datum",
                        value: formatDate(cancellation.issuedOn),
                      },
                    ]
                  : []),
                ...refundItems,
              ]}
            />
            <div className="inv-note">
              <StoredDocument
                actionId={invoice.actionId}
                client={client}
                kind="cancellation"
                record={row.cancellationDocument}
              />
            </div>
          </>
        ) : (
          <>
            <p className="small muted">
              Diese Rechnung wurde storniert, bevor LeonAid Stornorechnungen
              ausgestellt hat. Deshalb gibt es zu ihr noch keine Stornorechnung.
            </p>
            {refundItems.length ? <DetailProps items={refundItems} /> : null}
            {canManageSettlement ? (
              <>
                <div className="cluster inv-section-actions">
                  <Button
                    data-testid="issue-cancellation-document"
                    icon={FileText}
                    loading={issue.isPending}
                    onClick={() => issue.mutate()}
                    size="sm"
                    variant="secondary"
                  >
                    Stornorechnung ausstellen
                  </Button>
                </div>
                <p className="small subtle inv-note">
                  Sie erhält die nächste Nummer aus dem Nummernkreis der
                  Rechnungen und das heutige Datum.
                </p>
              </>
            ) : null}
          </>
        )}
        {errorMessage ? (
          <p className="small inv-error" role="alert">
            {errorMessage}
          </p>
        ) : null}
      </div>
    </DetailSection>
  );
}

function dueText(dueOn: string, today: string) {
  const relative = relativeDay(dueOn, today);
  const short = shortDate(dueOn, today);
  return relative === short ? short : `${short} (${relative})`;
}

/** Prototype callout: a failed delivery with the explicit resend command. */
function FailedDeliveryCallout({
  client,
  delivery,
  kind,
  onChanged,
  record,
}: {
  readonly client: LeonAidApiClient;
  readonly delivery: InvoiceDeliveryResponse;
  readonly kind: DeliveryKind;
  readonly onChanged: () => void;
  readonly record: InvoiceRecordResponse;
}) {
  const [errorMessage, setErrorMessage] = useState<string>();
  const words = deliveryKinds[kind];
  const retry = useMutation({
    // The retry of a cancellation invoice needs a fresh login; the error
    // helper sends the person there and back.
    mutationFn: () =>
      kind === "cancellation"
        ? client.retryInvoiceCancellationDelivery(
            record.invoice.actionId,
            record.invoice.id,
            delivery.id,
          )
        : client.retryInvoiceDelivery(
            record.invoice.actionId,
            record.invoice.id,
            delivery.id,
          ),
    onError(cause) {
      setErrorMessage(actionErrorMessage(cause).message);
    },
    onSuccess() {
      setErrorMessage(undefined);
      onChanged();
    },
  });
  const email = delivery.recipientEmail ?? record.invoice.recipient.email;
  return (
    <div className="callout tone-danger inv-callout" role="status">
      <Icon icon={Mail} size={16} />
      <span className="grow">
        {words.failedSubject} an {email ?? "den Empfänger"} fehlgeschlagen
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
          data-testid={words.retryTestId}
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

/**
 * The e-mail delivery of one document: the invoice, or its cancellation
 * invoice. Both flows share the states, the log and the commands.
 */
function InvoiceDelivery({
  canManage,
  client,
  deliveries,
  documentAvailable,
  kind,
  onChanged,
  record,
}: {
  readonly canManage: boolean;
  readonly client: LeonAidApiClient;
  /** The deliveries of this document, newest first. */
  readonly deliveries: readonly InvoiceDeliveryResponse[];
  readonly documentAvailable: boolean;
  readonly kind: DeliveryKind;
  readonly onChanged: () => void;
  readonly record: InvoiceRecordResponse;
}) {
  const { invoice } = record;
  const words = deliveryKinds[kind];
  const [errorMessage, setErrorMessage] = useState<string>();
  const [confirmResend, setConfirmResend] = useState(false);
  const latest = deliveries[0];
  const recipientEmail = latest?.recipientEmail ?? invoice.recipient.email;
  const storageKey =
    kind === "cancellation"
      ? cancellationDeliveryCommandStorageKey(invoice.id)
      : deliveryCommandStorageKey(invoice.id);
  const send = useMutation({
    mutationFn: () =>
      kind === "cancellation"
        ? client.sendInvoiceCancellation(invoice.actionId, invoice.id, {
            headers: {
              "Idempotency-Key": commandKey(
                storageKey,
                "invoice:cancellation-delivery",
              ),
            },
          })
        : client.sendInvoice(invoice.actionId, invoice.id, {
            headers: { "Idempotency-Key": commandKey(storageKey, "poc094") },
          }),
    onError(cause) {
      setErrorMessage(actionErrorMessage(cause).message);
    },
    onSuccess() {
      forgetCommandKey(storageKey);
      setConfirmResend(false);
      setErrorMessage(undefined);
      onChanged();
    },
  });
  const status = latest ? deliveryStatus[latest.status] : undefined;
  const description = latest
    ? (words.descriptions[latest.status] ?? status?.description)
    : words.notSent;
  // A cancelled invoice is no longer sent; its cancellation invoice is.
  const cancelled = kind === "invoice" && invoice.status === "cancelled";

  return (
    <section
      aria-busy={send.isPending}
      className="pane-section"
      data-state={latest?.status ?? "not-sent"}
      data-testid={words.testId}
    >
      <h3>{words.title}</h3>
      <DetailProps
        items={[
          {
            label: "Status",
            value: status?.label ?? "Noch nicht versendet",
          },
          {
            label: "Empfänger",
            value: recipientEmail ? (
              <WrapEmail value={recipientEmail} />
            ) : (
              "Keine E-Mail-Adresse hinterlegt"
            ),
          },
        ]}
      />
      <p className="small subtle inv-note">{description}</p>

      {deliveries.length ? (
        <ol aria-label="Versandprotokoll" className="timeline inv-attempts">
          {deliveries.map((delivery, index) => (
            <li
              data-status={delivery.status}
              data-testid={`${words.testId}-attempt`}
              key={delivery.id}
            >
              <span>
                <strong>
                  {index === 0 ? "Aktueller Versand" : "Früherer Versand"}
                </strong>{" "}
                · {deliveryStatus[delivery.status].label}
                <span className="inv-attempt-subject">{delivery.subject}</span>
                {delivery.messageId ? (
                  <code
                    className="inv-attempt-code"
                    data-testid="invoice-delivery-message-id"
                  >
                    Message-ID {delivery.messageId}
                  </code>
                ) : null}
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

      {canManage &&
      !cancelled &&
      !latest &&
      documentAvailable &&
      recipientEmail ? (
        <div className="cluster inv-section-actions">
          <Button
            data-testid={words.sendTestId}
            icon={Send}
            loading={send.isPending}
            onClick={() => send.mutate()}
            size="sm"
            variant="secondary"
          >
            {words.send}
          </Button>
        </div>
      ) : null}

      {canManage &&
      !cancelled &&
      latest?.status === "sent" &&
      !confirmResend ? (
        <div className="cluster inv-section-actions">
          <Button
            data-testid={words.resendTestId}
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
          className="callout inv-confirm"
          role="group"
          aria-label="Erneut senden bestätigen"
        >
          <div className="stack">
            <p>
              Es geht eine zweite E-Mail mit derselben PDF-Version an{" "}
              <strong>{recipientEmail}</strong>.
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
                data-testid={words.confirmResendTestId}
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

      {canManage && !cancelled && !latest && !documentAvailable ? (
        <p className="small muted inv-note">{words.waitsForDocument}</p>
      ) : null}
      {canManage && !cancelled && !recipientEmail ? (
        <p className="small muted inv-note">
          Für den Versand fehlt eine E-Mail-Adresse im gespeicherten
          Rechnungsempfänger.
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

/** The invoice PDF row: open in the browser, or download the stored file. */
export function InvoiceDocument({
  actionId,
  client,
  row,
}: {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  readonly row: InvoiceRow;
}) {
  return (
    <StoredDocument
      actionId={actionId}
      client={client}
      kind="invoice"
      record={row.document}
    />
  );
}

/** The words and test ids of the two stored PDFs of an invoice. */
const documentKinds = {
  invoice: {
    testId: "invoice-document",
    previewTestId: "preview-document",
    downloadTestId: "download-document",
    fallbackFilename: "Rechnung.pdf",
    missing:
      "Das PDF ist noch nicht angelegt. Der Dokumentauftrag muss geprüft werden.",
    pending:
      "Das PDF wird gerade erzeugt und danach unveränderlich gespeichert.",
  },
  cancellation: {
    testId: "cancellation-document",
    previewTestId: "preview-cancellation-document",
    downloadTestId: "download-cancellation-document",
    fallbackFilename: "Stornorechnung.pdf",
    missing:
      "Das PDF der Stornorechnung ist noch nicht angelegt. Der Dokumentauftrag muss geprüft werden.",
    pending:
      "Das PDF der Stornorechnung wird gerade erzeugt und danach unveränderlich gespeichert.",
  },
} as const;

/** One stored PDF in its state: missing, being rendered, removed or ready. */
function StoredDocument({
  actionId,
  client,
  kind,
  record,
}: {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  readonly kind: DeliveryKind;
  readonly record: GeneratedDocumentRecordResponse | undefined;
}) {
  const words = documentKinds[kind];
  const generated = record?.document;
  if (!generated) {
    return (
      <p
        className="small muted"
        data-state="missing"
        data-testid={words.testId}
      >
        {words.missing}
      </p>
    );
  }
  if (generated.status === "pending") {
    return (
      <p
        aria-live="polite"
        className="small muted"
        data-state="pending"
        data-testid={words.testId}
      >
        {words.pending}
      </p>
    );
  }
  if (generated.status === "deleted") {
    return (
      <p
        className="small muted"
        data-state="deleted"
        data-testid={words.testId}
      >
        {generated.filename ?? "Das PDF"} wurde kontrolliert entfernt.
      </p>
    );
  }
  return (
    <DocumentListItem
      actionId={actionId}
      client={client}
      document={generated}
      kind={kind}
    />
  );
}

type AvailableDocument = NonNullable<InvoiceRow["document"]>["document"];

function DocumentListItem({
  actionId,
  client,
  document: generated,
  kind,
}: {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  readonly document: AvailableDocument;
  readonly kind: DeliveryKind;
}) {
  const words = documentKinds[kind];
  const filename = generated.filename ?? words.fallbackFilename;
  const { download, errorMessage, busy } = useDocumentDownload(
    client,
    actionId,
    generated.id,
    filename,
  );
  const createdAt = generated.availableAt ?? generated.createdAt;
  return (
    <ul
      aria-busy={busy || undefined}
      className="doc-list"
      data-state="available"
      data-testid={words.testId}
    >
      <li>
        <Icon icon={FileText} size={16} />
        <span className="grow">
          {filename}
          <span
            className="subtle small"
            data-testid="invoice-document-metadata"
          >
            {" "}
            · PDF · {formatFileSize(generated.sizeBytes ?? 0)} · Version{" "}
            {generated.version} · erzeugt {formatDateTime(createdAt)}
          </span>
        </span>
        <a
          aria-label={`${filename} im Browser öffnen`}
          className={buttonClassName({ size: "sm", variant: "ghost" })}
          data-testid={words.previewTestId}
          href={documentPreviewHref(actionId, generated.id)}
          rel="noopener noreferrer"
          target="_blank"
        >
          <Icon icon={FileText} size={16} />
          <span className="btn-label">Öffnen</span>
        </a>
        <Button
          aria-label={`${filename} herunterladen`}
          data-testid={words.downloadTestId}
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

export function documentPreviewHref(actionId: string, documentId: string) {
  return `/api/v1/actions/${encodeURIComponent(actionId)}/documents/${encodeURIComponent(documentId)}/download?inline=true`;
}

/** Downloads a stored PDF through the API client (authorization stays server side). */
export function useDocumentDownload(
  client: LeonAidApiClient,
  actionId: string,
  documentId: string,
  filename: string,
) {
  const [busy, setBusy] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string>();
  async function download() {
    setBusy(true);
    setErrorMessage(undefined);
    try {
      const blob = await client.downloadGeneratedDocument(actionId, documentId);
      const objectUrl = URL.createObjectURL(blob);
      const anchor = globalThis.document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = filename;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
    } catch (error) {
      setErrorMessage(
        error instanceof ApiError &&
          error.detail.code === "generated_document_storage_missing"
          ? "Die gespeicherte PDF-Version fehlt. Der Vorgang muss technisch geprüft werden."
          : "Das PDF konnte gerade nicht geladen werden. Versuchen Sie es erneut.",
      );
    } finally {
      setBusy(false);
    }
  }
  return { busy, download, errorMessage };
}

/** Lets long addresses break only after "@" and before dots. */
export function WrapEmail({ value }: { readonly value: string }) {
  const parts = value.split(/(?=[.@])/);
  return (
    <span className="wrap-email">
      {parts.map((part, index) => (
        <span key={index}>
          {index > 0 ? <wbr /> : null}
          {part}
        </span>
      ))}
    </span>
  );
}
