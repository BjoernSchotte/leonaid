import { useMutation } from "@tanstack/react-query";
import { Download, FileText, Mail, Send } from "lucide-react";
import { useState } from "react";

import type {
  DonationDeliveryResponse,
  DonationPledgeDocumentResponse,
  DonationResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, buttonClassName, DetailProps, Icon } from "@leonaid/ui";

import {
  documentPreviewHref,
  useDocumentDownload,
  WrapEmail,
} from "../invoices/invoice-detail";
import { formatDateTime, formatFileSize } from "../invoices/invoice-format";
import { commandKey, forgetCommandKey } from "../invoices/invoice-model";
import { donationErrorMessage } from "./donation-model";

/**
 * The two documents of a donation that have a PDF and a mail: the pledge
 * ("Spendenzusage") and the receipt ("Zuwendungsbestätigung"). The kind is
 * part of every test id; the noun is the German word in the copy.
 */
export interface DonationDocumentKind {
  /** "receipt-void" is the PDF of a voided receipt: stored, never sent. */
  readonly kind: "pledge" | "receipt" | "receipt-void";
  readonly noun: "Spendenzusage" | "Zuwendungsbestätigung";
}

export const PLEDGE: DonationDocumentKind = {
  kind: "pledge",
  noun: "Spendenzusage",
};
export const RECEIPT: DonationDocumentKind = {
  kind: "receipt",
  noun: "Zuwendungsbestätigung",
};
export const VOID_RECEIPT: DonationDocumentKind = {
  kind: "receipt-void",
  noun: "Zuwendungsbestätigung",
};

const deliveryStatus = {
  failed: {
    label: "Versand fehlgeschlagen",
    description: (noun: string) =>
      `Die E-Mail wurde nicht zugestellt. Die ${noun} bleibt unverändert und kann kontrolliert erneut gesendet werden.`,
  },
  queued: {
    label: "Für Versand eingeplant",
    description: () =>
      "Der Versandauftrag ist gespeichert und wird vom Hintergrunddienst übernommen.",
  },
  retrying: {
    label: "Automatischer Neuversuch",
    description: () =>
      "Der letzte Versuch ist fehlgeschlagen. LeonAid versucht die Zustellung erneut.",
  },
  sending: {
    label: "Wird gerade versendet",
    description: (noun: string) =>
      `Das gespeicherte PDF der ${noun} wird jetzt an den Spender übertragen.`,
  },
  sent: {
    label: "Erfolgreich versendet",
    description: () =>
      "Der Mailserver hat die Nachricht mit genau dieser PDF-Version angenommen.",
  },
} as const;

/** A stored PDF in its state: being rendered, removed or ready. */
export function DonationDocument({
  actionId,
  client,
  document: generated,
  fallbackFilename,
  kind,
}: {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  readonly document: DonationPledgeDocumentResponse;
  /** The download name while the server has not stored one. */
  readonly fallbackFilename: string;
  readonly kind: DonationDocumentKind;
}) {
  const testId = `donation-${kind.kind}-document`;
  if (generated.status === "pending") {
    return (
      <p
        aria-live="polite"
        className="small muted"
        data-state="pending"
        data-testid={testId}
      >
        Das PDF der {kind.noun} wird erzeugt und danach unveränderlich
        gespeichert.
      </p>
    );
  }
  if (generated.status === "deleted") {
    return (
      <p className="small muted" data-state="deleted" data-testid={testId}>
        {generated.filename ?? "Das PDF"} wurde kontrolliert entfernt.
      </p>
    );
  }
  return (
    <AvailableDocument
      actionId={actionId}
      client={client}
      documentId={generated.id}
      filename={generated.filename ?? fallbackFilename}
      kind={kind}
      producedAt={generated.availableAt ?? generated.createdAt}
      sizeBytes={generated.sizeBytes}
      version={generated.version}
    />
  );
}

function AvailableDocument({
  actionId,
  client,
  documentId,
  filename,
  kind,
  producedAt,
  sizeBytes,
  version,
}: {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  readonly documentId: string;
  readonly filename: string;
  readonly kind: DonationDocumentKind;
  readonly producedAt: string;
  readonly sizeBytes: number | null;
  readonly version: number;
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
      data-testid={`donation-${kind.kind}-document`}
    >
      <li>
        <Icon icon={FileText} size={16} />
        <span className="grow">
          {filename}
          <span
            className="subtle small"
            data-testid={`donation-${kind.kind}-document-metadata`}
          >
            {" "}
            · PDF{sizeBytes != null ? ` · ${formatFileSize(sizeBytes)}` : ""} ·
            Version {version} · erzeugt {formatDateTime(producedAt)}
          </span>
        </span>
        <a
          aria-label={`${filename} im Browser öffnen`}
          className={buttonClassName({ size: "sm", variant: "ghost" })}
          data-testid={`preview-donation-${kind.kind}`}
          href={documentPreviewHref(actionId, documentId)}
          rel="noopener noreferrer"
          target="_blank"
        >
          <Icon icon={FileText} size={16} />
          <span className="btn-label">Öffnen</span>
        </a>
        <Button
          aria-label={`${filename} herunterladen`}
          data-testid={`download-donation-${kind.kind}`}
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

/** A failed pledge or receipt mail with the explicit retry command. */
export function FailedDonationDelivery({
  client,
  delivery,
  donation,
  kind,
  onChanged,
}: {
  readonly client: LeonAidApiClient;
  readonly delivery: DonationDeliveryResponse;
  readonly donation: DonationResponse;
  readonly kind: DonationDocumentKind;
  readonly onChanged: () => void;
}) {
  const [errorMessage, setErrorMessage] = useState<string>();
  const retry = useMutation({
    // One retry command serves every delivery of a donation. No
    // Idempotency-Key, as for the invoice retry: only a failed delivery can
    // be started again, so a second call finds nothing to retry.
    mutationFn: () =>
      client.retryDonationPledgeDelivery(
        donation.actionId,
        donation.id,
        delivery.id,
      ),
    onError(cause) {
      const message = donationErrorMessage(cause);
      setErrorMessage(message.message);
      if (message.conflict) onChanged();
    },
    onSuccess() {
      setErrorMessage(undefined);
      onChanged();
    },
  });
  return (
    <div
      className="callout tone-danger inv-callout"
      data-testid={`donation-${kind.kind}-delivery-failed`}
      role="status"
    >
      <Icon icon={Mail} size={16} />
      <span className="grow">
        Versand der {kind.noun} an {delivery.recipientEmail} fehlgeschlagen
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
          data-testid={`retry-donation-${kind.kind}-delivery`}
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
 * The e-mail delivery of a pledge or a receipt: state, log and the send
 * commands.
 */
export function DonationDelivery({
  blocked,
  deliveries,
  documentAvailable,
  donorEmail,
  idempotencyPrefix,
  kind,
  maySend,
  onChanged,
  send: sendDocument,
  storageKey,
}: {
  /** No new mail at all, e.g. for a cancelled donation. */
  readonly blocked: boolean;
  /** Newest first. */
  readonly deliveries: readonly DonationDeliveryResponse[];
  readonly documentAvailable: boolean;
  readonly donorEmail: string | null;
  /** Prefix of the Idempotency-Key, e.g. "donation:pledge-delivery". */
  readonly idempotencyPrefix: string;
  readonly kind: DonationDocumentKind;
  /** Server right `maySend`. */
  readonly maySend: boolean;
  readonly onChanged: () => void;
  readonly send: (options: {
    readonly headers: Record<string, string>;
  }) => Promise<unknown>;
  /** Session storage key of the command's Idempotency-Key. */
  readonly storageKey: string;
}) {
  const [errorMessage, setErrorMessage] = useState<string>();
  const [confirmResend, setConfirmResend] = useState(false);
  const latest = deliveries[0];
  const { noun } = kind;
  const send = useMutation({
    mutationFn: () =>
      sendDocument({
        headers: {
          "Idempotency-Key": commandKey(storageKey, idempotencyPrefix),
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
  const canSend = maySend && !blocked && documentAvailable && donorEmail;

  return (
    <section
      aria-busy={send.isPending}
      className="pane-section"
      data-state={latest?.status ?? "not-sent"}
      data-testid={`donation-${kind.kind}-delivery`}
    >
      <h3>Versand der {noun}</h3>
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
        {status?.description(noun) ??
          `Das unveränderliche PDF der ${noun} geht direkt an die E-Mail-Adresse des Spenders.`}
      </p>

      {deliveries.length ? (
        <ol aria-label="Versandprotokoll" className="timeline inv-attempts">
          {deliveries.map((delivery, index) => (
            <li
              data-status={delivery.status}
              data-testid={`donation-${kind.kind}-delivery-attempt`}
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
            data-testid={`send-donation-${kind.kind}`}
            icon={Send}
            loading={send.isPending}
            onClick={() => send.mutate()}
            size="sm"
            variant="secondary"
          >
            {noun} senden
          </Button>
        </div>
      ) : null}

      {canSend && latest?.status === "sent" && !confirmResend ? (
        <div className="cluster inv-section-actions">
          <Button
            data-testid={`resend-donation-${kind.kind}`}
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
                data-testid={`confirm-resend-donation-${kind.kind}`}
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

      {maySend && !blocked && donorEmail && !latest && !documentAvailable ? (
        <p className="small muted inv-note">
          Der Versand ist möglich, sobald das PDF der {noun} bereitsteht.
        </p>
      ) : null}
      {!blocked && !donorEmail ? (
        <p
          className="small muted inv-note"
          data-testid={
            kind.kind === "pledge"
              ? "donation-donor-email-missing"
              : `donation-${kind.kind}-donor-email-missing`
          }
        >
          Für den Versand fehlt die E-Mail-Adresse des Spenders. Senden Sie die{" "}
          {noun} auf anderem Weg, zum Beispiel als ausgedrucktes PDF.
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
