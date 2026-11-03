import { useMutation } from "@tanstack/react-query";
import {
  Ban,
  Download,
  FileText,
  Lock,
  Mail,
  Send,
  Wallet,
} from "lucide-react";
import { useState } from "react";

import {
  ApiError,
  type InvoiceDeliveryResponse,
  type InvoiceRecordResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Button,
  buttonClassName,
  DetailProps,
  DetailSection,
  Icon,
  StatusLabel,
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
  commandKey,
  deliveryCommandStorageKey,
  forgetCommandKey,
  invoiceDispatchLabels,
  invoiceStatusLabels,
  type InvoiceRow,
} from "./invoice-model";

export type InvoiceCommand = "payment" | "cancellation";

export interface InvoiceDetailProps {
  readonly row: InvoiceRow;
  readonly client: LeonAidApiClient;
  /** Server right `mayIssue`: send, resend and retry the e-mail delivery. */
  readonly canManageDelivery: boolean;
  /** Server right `mayManageSettlements`: payment and cancellation. */
  readonly canManageSettlement: boolean;
  readonly onCommand: (command: InvoiceCommand, row: InvoiceRow) => void;
  readonly onChanged: () => void;
  readonly today: string;
}

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
  const { invoice, payment, cancellation } = record;
  const settlement = cancellation
    ? "cancelled"
    : payment
      ? "paid"
      : "outstanding";
  const latest = record.deliveries[0];

  return (
    <div
      className="inv-detail"
      data-invoice-id={invoice.id}
      data-settlement={settlement}
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
      ) : payment ? (
        <div className="inv-stamp-row" data-testid="invoice-stamp">
          <span className="stamp tone-ok">Bezahlt</span>
          <span className="small muted">
            Zahlungseingang am {shortDate(payment.receivedOn, today)},
            vollständig.
          </span>
        </div>
      ) : null}

      {canManageSettlement && settlement === "outstanding" ? (
        <div className="next-step">
          <p>
            <strong>
              {row.status === "overdue"
                ? `Seit ${shortDate(invoice.dueOn, today)} überfällig.`
                : `Fällig ${relativeDay(invoice.dueOn, today)}.`}
            </strong>{" "}
            Erfassen Sie den Zahlungseingang, sobald der volle Betrag da ist.
          </p>
          <div className="cluster">
            <Button
              data-testid="open-payment-form"
              icon={Wallet}
              onClick={() => onCommand("payment", row)}
              variant="primary"
            >
              Zahlung erfassen
            </Button>
            <Button
              data-testid="open-cancellation-form"
              icon={Ban}
              onClick={() => onCommand("cancellation", row)}
              variant="ghost"
            >
              Stornieren
            </Button>
          </div>
        </div>
      ) : null}

      {canManageSettlement && settlement === "paid" ? (
        <div className="cluster">
          <Button
            data-testid="open-cancellation-form"
            icon={Ban}
            onClick={() => onCommand("cancellation", row)}
            size="sm"
            variant="ghost"
          >
            Stornieren
          </Button>
        </div>
      ) : null}

      {canManageDelivery && latest?.status === "failed" ? (
        <FailedDeliveryCallout
          client={client}
          delivery={latest}
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
            {
              label: "Offen",
              value: (
                <span className="num" data-testid="invoice-open-amount">
                  {formatMoney(record.openMinor, invoice.currency)}
                </span>
              ),
            },
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
                  href={`/admin/orders?action=${encodeURIComponent(invoice.actionId)}&open=${encodeURIComponent(invoice.commitmentId)}`}
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

      {payment ? (
        <DetailSection title="Zahlung">
          <div data-testid="payment-record">
            <DetailProps
              items={[
                {
                  label: "Betrag",
                  value: (
                    <span className="num">
                      {formatMoney(payment.amountMinor, payment.currency)}
                    </span>
                  ),
                },
                { label: "Eingegangen", value: formatDate(payment.receivedOn) },
                { label: "Verwendungszweck", value: payment.reference },
                {
                  label: "Erfasst",
                  value: `${payment.recordedByDisplayName ?? "Berechtigte Finanzrolle"}, ${formatDateTime(payment.recordedAt)}`,
                },
              ]}
            />
          </div>
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

      <InvoiceDelivery
        canManage={canManageDelivery}
        client={client}
        documentAvailable={row.document?.document.status === "available"}
        onChanged={onChanged}
        record={record}
      />

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

function dueText(dueOn: string, today: string) {
  const relative = relativeDay(dueOn, today);
  const short = shortDate(dueOn, today);
  return relative === short ? short : `${short} (${relative})`;
}

/** Prototype callout: a failed delivery with the explicit resend command. */
function FailedDeliveryCallout({
  client,
  delivery,
  onChanged,
  record,
}: {
  readonly client: LeonAidApiClient;
  readonly delivery: InvoiceDeliveryResponse;
  readonly onChanged: () => void;
  readonly record: InvoiceRecordResponse;
}) {
  const [errorMessage, setErrorMessage] = useState<string>();
  const retry = useMutation({
    mutationFn: () =>
      client.retryInvoiceDelivery(
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
        Versand an {email ?? "den Empfänger"} fehlgeschlagen
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
          data-testid="retry-invoice-delivery"
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

function InvoiceDelivery({
  canManage,
  client,
  documentAvailable,
  onChanged,
  record,
}: {
  readonly canManage: boolean;
  readonly client: LeonAidApiClient;
  readonly documentAvailable: boolean;
  readonly onChanged: () => void;
  readonly record: InvoiceRecordResponse;
}) {
  const { invoice } = record;
  const [errorMessage, setErrorMessage] = useState<string>();
  const [confirmResend, setConfirmResend] = useState(false);
  const latest = record.deliveries[0];
  const recipientEmail = latest?.recipientEmail ?? invoice.recipient.email;
  const storageKey = deliveryCommandStorageKey(invoice.id);
  const send = useMutation({
    mutationFn: () =>
      client.sendInvoice(invoice.actionId, invoice.id, {
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
  const cancelled = invoice.status === "cancelled";

  return (
    <section
      aria-busy={send.isPending}
      className="pane-section"
      data-state={latest?.status ?? "not-sent"}
      data-testid="invoice-delivery"
    >
      <h3>Versand</h3>
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
      <p className="small subtle inv-note">
        {status?.description ??
          "Das unveränderliche Rechnungs-PDF geht direkt an den gespeicherten Empfänger."}
      </p>

      {record.deliveries.length ? (
        <ol aria-label="Versandprotokoll" className="timeline inv-attempts">
          {record.deliveries.map((delivery, index) => (
            <li
              data-status={delivery.status}
              data-testid="invoice-delivery-attempt"
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
            data-testid="send-invoice"
            icon={Send}
            loading={send.isPending}
            onClick={() => send.mutate()}
            size="sm"
            variant="secondary"
          >
            Rechnung senden
          </Button>
        </div>
      ) : null}

      {canManage &&
      !cancelled &&
      latest?.status === "sent" &&
      !confirmResend ? (
        <div className="cluster inv-section-actions">
          <Button
            data-testid="resend-invoice"
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
                data-testid="confirm-resend-invoice"
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
        <p className="small muted inv-note">
          Der Versand ist möglich, sobald das Rechnungs-PDF bereitsteht.
        </p>
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
  const generated = row.document?.document;
  if (!generated) {
    return (
      <p
        className="small muted"
        data-state="missing"
        data-testid="invoice-document"
      >
        Das PDF ist noch nicht angelegt. Der Dokumentauftrag muss geprüft
        werden.
      </p>
    );
  }
  if (generated.status === "pending") {
    return (
      <p
        aria-live="polite"
        className="small muted"
        data-state="pending"
        data-testid="invoice-document"
      >
        Das PDF wird gerade erzeugt und danach unveränderlich gespeichert.
      </p>
    );
  }
  if (generated.status === "deleted") {
    return (
      <p
        className="small muted"
        data-state="deleted"
        data-testid="invoice-document"
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
    />
  );
}

type AvailableDocument = NonNullable<InvoiceRow["document"]>["document"];

function DocumentListItem({
  actionId,
  client,
  document: generated,
}: {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  readonly document: AvailableDocument;
}) {
  const { download, errorMessage, busy } = useDocumentDownload(
    client,
    actionId,
    generated.id,
    generated.filename ?? "Rechnung.pdf",
  );
  const filename = generated.filename ?? "Rechnung.pdf";
  const createdAt = generated.availableAt ?? generated.createdAt;
  return (
    <ul
      aria-busy={busy || undefined}
      className="doc-list"
      data-state="available"
      data-testid="invoice-document"
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
          data-testid="preview-document"
          href={documentPreviewHref(actionId, generated.id)}
          rel="noopener noreferrer"
          target="_blank"
        >
          <Icon icon={FileText} size={16} />
          <span className="btn-label">Öffnen</span>
        </a>
        <Button
          aria-label={`${filename} herunterladen`}
          data-testid="download-document"
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
