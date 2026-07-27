import {
  AddMoneyCircleIcon,
  Alert02Icon,
  Calendar03Icon,
  CancelCircleIcon,
  CheckmarkCircle02Icon,
  Download04Icon,
  FileViewIcon,
  Invoice03Icon,
  Mail02Icon,
  MailSend02Icon,
  Pdf02Icon,
  Refresh01Icon,
  UserMultiple02Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import {
  ApiError,
  type CurrentIdentityResponse,
  type GeneratedDocumentRecordResponse,
  type InvoiceDeliveryResponse,
  type InvoiceRecordResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

import { actionErrorMessage } from "../action-admin/errors";

interface InvoiceAdminPageProps {
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
}

const invoiceStatusLabels = {
  cancelled: "Storniert",
  issued: "Freigegeben",
  paid: "Bezahlt",
  sent: "Versendet",
} as const;

function formatMoney(amountMinor: number, currency: string) {
  return new Intl.NumberFormat("de-DE", {
    currency,
    style: "currency",
  }).format(amountMinor / 100);
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("de-DE", {
    dateStyle: "medium",
    timeZone: "Europe/Berlin",
  }).format(new Date(value));
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("de-DE", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Europe/Berlin",
  }).format(new Date(value));
}

function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"] as const;
  let value = bytes / 1024;
  let unit: (typeof units)[number] = units[0];
  for (const candidate of units.slice(1)) {
    if (value < 1024) break;
    value /= 1024;
    unit = candidate;
  }
  return `${new Intl.NumberFormat("de-DE", {
    maximumFractionDigits: value < 10 ? 1 : 0,
  }).format(value)} ${unit}`;
}

function deliveryCommandKey(invoiceId: string) {
  const storageKey = `leonaid.invoice-delivery-command.${invoiceId}`;
  const stored = window.sessionStorage.getItem(storageKey);
  if (stored) return stored;
  const value = `poc094:${crypto.randomUUID()}`;
  window.sessionStorage.setItem(storageKey, value);
  return value;
}

function settlementCommandKey(
  invoiceId: string,
  kind: "cancellation" | "payment",
) {
  const storageKey = `leonaid.invoice-${kind}-command.${invoiceId}`;
  const stored = window.sessionStorage.getItem(storageKey);
  if (stored) return stored;
  const value = `poc095:${kind}:${crypto.randomUUID()}`;
  window.sessionStorage.setItem(storageKey, value);
  return value;
}

function localIsoDate() {
  return new Intl.DateTimeFormat("en-CA", {
    day: "2-digit",
    month: "2-digit",
    timeZone: "Europe/Berlin",
    year: "numeric",
  }).format(new Date());
}

const deliveryStatus = {
  failed: {
    label: "Versand fehlgeschlagen",
    description:
      "Die E-Mail wurde nicht zugestellt. Der Beleg bleibt unverändert und kann kontrolliert neu gestartet werden.",
  },
  queued: {
    label: "Für Versand eingeplant",
    description:
      "Der Versandauftrag ist dauerhaft gespeichert und wird vom Hintergrunddienst übernommen.",
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

function InvoiceDocumentPanel({
  actionId,
  client,
  record,
}: {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  readonly record?: GeneratedDocumentRecordResponse;
}) {
  const [busy, setBusy] = useState<"download" | "preview">();
  const [errorMessage, setErrorMessage] = useState<string>();
  const generated = record?.document;

  if (!generated) {
    return (
      <section className="invoice-document" data-state="missing">
        <span aria-hidden="true" className="invoice-document__mark">
          <HugeiconsIcon icon={Pdf02Icon} size={22} strokeWidth={1.8} />
        </span>
        <div className="invoice-document__identity">
          <small>Rechnungs-PDF</small>
          <strong>Noch nicht angelegt</strong>
          <p>
            Die Rechnung ist gespeichert. Der Dokumentauftrag muss geprüft
            werden.
          </p>
        </div>
      </section>
    );
  }

  if (generated.status === "pending") {
    return (
      <section
        aria-live="polite"
        className="invoice-document"
        data-state="pending"
        data-testid="invoice-document"
      >
        <span aria-hidden="true" className="invoice-document__mark">
          <HugeiconsIcon icon={Pdf02Icon} size={22} strokeWidth={1.8} />
        </span>
        <div className="invoice-document__identity">
          <small>Rechnungs-PDF</small>
          <strong>Wird gerade erzeugt</strong>
          <p>
            LeonAid rendert den freigegebenen Stand und speichert ihn
            unveränderlich.
          </p>
        </div>
        <span className="invoice-document__status">In Arbeit</span>
      </section>
    );
  }

  if (generated.status === "deleted") {
    return (
      <section
        className="invoice-document"
        data-state="deleted"
        data-testid="invoice-document"
      >
        <span aria-hidden="true" className="invoice-document__mark">
          <HugeiconsIcon icon={Pdf02Icon} size={22} strokeWidth={1.8} />
        </span>
        <div className="invoice-document__identity">
          <small>Rechnungs-PDF</small>
          <strong>{generated.filename ?? "Entferntes Dokument"}</strong>
          <p>Diese Dokumentversion wurde kontrolliert entfernt.</p>
        </div>
        <span className="invoice-document__status">Entfernt</span>
      </section>
    );
  }

  const availableDocument = generated;
  const filename = availableDocument.filename ?? "Rechnung.pdf";
  const createdAt =
    availableDocument.availableAt ?? availableDocument.createdAt;

  async function provideDocument(mode: "download" | "preview") {
    const previewWindow =
      mode === "preview" ? window.open("about:blank", "_blank") : null;
    if (mode === "preview" && !previewWindow) {
      setErrorMessage(
        "Die Vorschau wurde vom Browser blockiert. Erlaube Pop-ups für LeonAid und versuche es erneut.",
      );
      return;
    }
    if (previewWindow) {
      previewWindow.opener = null;
      previewWindow.document.title = "PDF wird geladen …";
    }
    setBusy(mode);
    setErrorMessage(undefined);
    try {
      const blob = await client.downloadGeneratedDocument(
        actionId,
        availableDocument.id,
        { inline: mode === "preview" },
      );
      const objectUrl = URL.createObjectURL(blob);
      if (previewWindow) {
        const previewDocument = previewWindow.document;
        previewDocument.title = filename;
        previewDocument.body.replaceChildren();
        previewDocument.body.style.margin = "0";
        previewDocument.body.style.background = "#171717";
        const frame = previewDocument.createElement("iframe");
        frame.src = objectUrl;
        frame.title = `Vorschau ${filename}`;
        frame.style.width = "100vw";
        frame.style.height = "100vh";
        frame.style.border = "0";
        previewDocument.body.append(frame);
      } else {
        const anchor = globalThis.document.createElement("a");
        anchor.href = objectUrl;
        anchor.download = filename;
        anchor.click();
      }
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
    } catch (error) {
      previewWindow?.close();
      setErrorMessage(
        error instanceof ApiError &&
          error.detail.code === "generated_document_storage_missing"
          ? "Die gespeicherte PDF-Version fehlt. Der Vorgang ist diagnostizierbar und muss technisch geprüft werden."
          : "Das PDF konnte gerade nicht sicher geladen werden. Versuche es erneut.",
      );
    } finally {
      setBusy(undefined);
    }
  }

  return (
    <section
      aria-busy={busy !== undefined}
      className="invoice-document"
      data-state="available"
      data-testid="invoice-document"
    >
      <span aria-hidden="true" className="invoice-document__mark">
        <HugeiconsIcon icon={Pdf02Icon} size={22} strokeWidth={1.8} />
      </span>
      <div className="invoice-document__identity">
        <small>Unveränderliches Rechnungs-PDF</small>
        <strong>{filename}</strong>
        <p data-testid="invoice-document-metadata">
          PDF · {formatFileSize(availableDocument.sizeBytes ?? 0)} · Version{" "}
          {availableDocument.version} · erzeugt {formatDateTime(createdAt)}
        </p>
      </div>
      <span className="invoice-document__status">Bereit</span>
      <div className="invoice-document__actions">
        <Button
          data-testid="preview-document"
          disabled={busy !== undefined}
          icon={
            <HugeiconsIcon icon={FileViewIcon} size={18} strokeWidth={1.8} />
          }
          onClick={() => void provideDocument("preview")}
          variant="primary"
        >
          {busy === "preview" ? "PDF wird geöffnet …" : "PDF öffnen"}
        </Button>
        <Button
          data-testid="download-document"
          disabled={busy !== undefined}
          icon={
            <HugeiconsIcon icon={Download04Icon} size={18} strokeWidth={1.8} />
          }
          onClick={() => void provideDocument("download")}
          variant="secondary"
        >
          {busy === "download" ? "Download läuft …" : "Herunterladen"}
        </Button>
      </div>
      {errorMessage ? (
        <p className="invoice-document__error" role="alert">
          {errorMessage}
        </p>
      ) : null}
    </section>
  );
}

function InvoiceDeliveryPanel({
  canManage,
  client,
  documentAvailable,
  invoice,
  onChanged,
}: {
  readonly canManage: boolean;
  readonly client: LeonAidApiClient;
  readonly documentAvailable: boolean;
  readonly invoice: InvoiceRecordResponse;
  readonly onChanged: () => void;
}) {
  const [errorMessage, setErrorMessage] = useState<string>();
  const [confirmResend, setConfirmResend] = useState(false);
  const latest = invoice.deliveries[0];
  const recipientEmail =
    latest?.recipientEmail ?? invoice.invoice.recipient.email;
  const send = useMutation({
    mutationFn: () =>
      client.sendInvoice(invoice.invoice.actionId, invoice.invoice.id, {
        headers: {
          "Idempotency-Key": deliveryCommandKey(invoice.invoice.id),
        },
      }),
    onError(cause) {
      setErrorMessage(actionErrorMessage(cause).message);
    },
    onSuccess() {
      window.sessionStorage.removeItem(
        `leonaid.invoice-delivery-command.${invoice.invoice.id}`,
      );
      setConfirmResend(false);
      setErrorMessage(undefined);
      onChanged();
    },
  });
  const retry = useMutation({
    mutationFn: (deliveryId: string) =>
      client.retryInvoiceDelivery(
        invoice.invoice.actionId,
        invoice.invoice.id,
        deliveryId,
      ),
    onError(cause) {
      setErrorMessage(actionErrorMessage(cause).message);
    },
    onSuccess() {
      setErrorMessage(undefined);
      onChanged();
    },
  });
  const busy = send.isPending || retry.isPending;
  const status = latest ? deliveryStatus[latest.status] : undefined;

  function statusIcon(delivery: InvoiceDeliveryResponse) {
    if (delivery.status === "sent") return CheckmarkCircle02Icon;
    if (delivery.status === "failed") return Alert02Icon;
    if (delivery.status === "retrying") return Refresh01Icon;
    return Mail02Icon;
  }

  return (
    <section
      aria-busy={busy}
      className="invoice-delivery"
      data-state={latest?.status ?? "not-sent"}
      data-testid="invoice-delivery"
    >
      <header className="invoice-delivery__header">
        <span aria-hidden="true" className="invoice-delivery__mark">
          <HugeiconsIcon icon={MailSend02Icon} size={22} strokeWidth={1.8} />
        </span>
        <div>
          <small>E-Mail-Versand</small>
          <strong>{status?.label ?? "Noch nicht versendet"}</strong>
          <p>
            {status?.description ??
              "Sende das unveränderliche Rechnungs-PDF direkt an den gespeicherten Empfänger."}
          </p>
        </div>
        {latest ? (
          <span
            className="invoice-delivery__status"
            data-status={latest.status}
          >
            {latest.status === "sent"
              ? "Zugestellt"
              : latest.status === "failed"
                ? "Handlung nötig"
                : "In Bearbeitung"}
          </span>
        ) : null}
      </header>

      <div className="invoice-delivery__recipient">
        <span>Empfänger</span>
        <strong>{recipientEmail ?? "Keine E-Mail-Adresse hinterlegt"}</strong>
      </div>

      {invoice.deliveries.length ? (
        <ol
          aria-label="Versandprotokoll"
          className="invoice-delivery__timeline"
        >
          {invoice.deliveries.map((delivery, index) => {
            const Icon = statusIcon(delivery);
            return (
              <li
                data-status={delivery.status}
                data-testid="invoice-delivery-attempt"
                key={delivery.id}
              >
                <span aria-hidden="true">
                  <HugeiconsIcon icon={Icon} size={17} strokeWidth={1.9} />
                </span>
                <div>
                  <strong>
                    {index === 0 ? "Aktueller Versand" : "Früherer Versand"}
                  </strong>
                  <small>{delivery.subject}</small>
                  <span>
                    Angelegt {formatDateTime(delivery.requestedAt)} ·{" "}
                    {delivery.attempts}{" "}
                    {delivery.attempts === 1 ? "Versuch" : "Versuche"}
                  </span>
                  {delivery.sentAt ? (
                    <span>Versendet {formatDateTime(delivery.sentAt)}</span>
                  ) : null}
                  {delivery.messageId ? (
                    <code data-testid="invoice-delivery-message-id">
                      Message-ID {delivery.messageId}
                    </code>
                  ) : null}
                  {delivery.lastErrorDetail ? (
                    <p
                      role={delivery.status === "failed" ? "alert" : undefined}
                    >
                      <strong>Letzter Fehler:</strong>{" "}
                      {delivery.lastErrorDetail}
                      {delivery.lastErrorCode
                        ? ` (${delivery.lastErrorCode})`
                        : ""}
                    </p>
                  ) : null}
                </div>
                {canManage && delivery.canRetry ? (
                  <Button
                    data-testid="retry-invoice-delivery"
                    disabled={busy}
                    icon={
                      <HugeiconsIcon
                        icon={Refresh01Icon}
                        size={18}
                        strokeWidth={1.8}
                      />
                    }
                    onClick={() => retry.mutate(delivery.id)}
                    variant="primary"
                  >
                    {retry.isPending
                      ? "Wird neu gestartet …"
                      : "Versand neu starten"}
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ol>
      ) : null}

      {canManage && !latest && documentAvailable && recipientEmail ? (
        <Button
          data-testid="send-invoice"
          disabled={busy}
          icon={
            <HugeiconsIcon icon={MailSend02Icon} size={18} strokeWidth={1.8} />
          }
          onClick={() => send.mutate()}
          variant="primary"
        >
          {send.isPending ? "Wird eingeplant …" : "Rechnung jetzt senden"}
        </Button>
      ) : null}

      {canManage && latest?.status === "sent" && !confirmResend ? (
        <Button
          data-testid="resend-invoice"
          disabled={busy}
          icon={
            <HugeiconsIcon icon={MailSend02Icon} size={18} strokeWidth={1.8} />
          }
          onClick={() => setConfirmResend(true)}
          variant="secondary"
        >
          Erneut senden
        </Button>
      ) : null}

      {confirmResend ? (
        <div className="invoice-delivery__confirm" role="group">
          <p>
            Es wird eine zweite E-Mail mit derselben PDF-Version an{" "}
            <strong>{recipientEmail}</strong> gesendet.
          </p>
          <div>
            <Button
              disabled={busy}
              onClick={() => setConfirmResend(false)}
              variant="secondary"
            >
              Abbrechen
            </Button>
            <Button
              data-testid="confirm-resend-invoice"
              disabled={busy}
              onClick={() => send.mutate()}
              variant="primary"
            >
              {send.isPending ? "Wird eingeplant …" : "Erneut senden"}
            </Button>
          </div>
        </div>
      ) : null}

      {canManage && !documentAvailable ? (
        <p className="invoice-delivery__hint">
          Der Versand ist möglich, sobald das Rechnungs-PDF bereitsteht.
        </p>
      ) : null}
      {canManage && !recipientEmail ? (
        <p className="invoice-delivery__hint">
          Für den Versand fehlt eine E-Mail-Adresse im unveränderlichen
          Rechnungsempfänger.
        </p>
      ) : null}
      {errorMessage ? (
        <p className="invoice-delivery__error" role="alert">
          {errorMessage}
        </p>
      ) : null}
    </section>
  );
}

function InvoiceSettlementPanel({
  canManage,
  client,
  onChanged,
  record,
}: {
  readonly canManage: boolean;
  readonly client: LeonAidApiClient;
  readonly onChanged: () => void;
  readonly record: InvoiceRecordResponse;
}) {
  const { invoice, payment, cancellation } = record;
  const [mode, setMode] = useState<"cancellation" | "payment">();
  const [amount, setAmount] = useState((invoice.grossMinor / 100).toFixed(2));
  const [receivedOn, setReceivedOn] = useState(localIsoDate);
  const [reference, setReference] = useState(invoice.paymentReference);
  const [reason, setReason] = useState("");
  const [confirmCancellation, setConfirmCancellation] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string>();
  const parsedAmount = Math.round(Number(amount.replace(",", ".")) * 100);
  const amountMatches =
    Number.isFinite(parsedAmount) && parsedAmount === invoice.grossMinor;
  const paymentMutation = useMutation({
    mutationFn: () =>
      client.recordInvoicePayment(
        invoice.actionId,
        invoice.id,
        {
          amountMinor: parsedAmount,
          currency: invoice.currency,
          receivedOn,
          reference,
        },
        {
          headers: {
            "Idempotency-Key": settlementCommandKey(invoice.id, "payment"),
          },
        },
      ),
    onError(cause) {
      setErrorMessage(actionErrorMessage(cause).message);
    },
    onSuccess() {
      window.sessionStorage.removeItem(
        `leonaid.invoice-payment-command.${invoice.id}`,
      );
      setMode(undefined);
      setErrorMessage(undefined);
      onChanged();
    },
  });
  const cancellationMutation = useMutation({
    mutationFn: () =>
      client.cancelInvoice(
        invoice.actionId,
        invoice.id,
        { reason },
        {
          headers: {
            "Idempotency-Key": settlementCommandKey(invoice.id, "cancellation"),
          },
        },
      ),
    onError(cause) {
      setErrorMessage(actionErrorMessage(cause).message);
    },
    onSuccess() {
      window.sessionStorage.removeItem(
        `leonaid.invoice-cancellation-command.${invoice.id}`,
      );
      setMode(undefined);
      setReason("");
      setConfirmCancellation(false);
      setErrorMessage(undefined);
      onChanged();
    },
  });
  const busy = paymentMutation.isPending || cancellationMutation.isPending;

  function chooseMode(next: "cancellation" | "payment") {
    setMode(next);
    setErrorMessage(undefined);
    if (next !== "cancellation") setConfirmCancellation(false);
  }

  return (
    <section
      aria-busy={busy}
      className="invoice-settlement"
      data-state={cancellation ? "cancelled" : payment ? "paid" : "outstanding"}
      data-testid="invoice-settlement"
    >
      <header className="invoice-settlement__header">
        <span aria-hidden="true" className="invoice-settlement__mark">
          <HugeiconsIcon
            icon={
              cancellation
                ? CancelCircleIcon
                : payment
                  ? CheckmarkCircle02Icon
                  : AddMoneyCircleIcon
            }
            size={22}
            strokeWidth={1.8}
          />
        </span>
        <div>
          <small>Zahlungsstatus</small>
          <strong>
            {cancellation
              ? "Dauerhaft storniert"
              : payment
                ? "Vollständig bezahlt"
                : `${formatMoney(record.openMinor, invoice.currency)} offen`}
          </strong>
          <p>
            {cancellation
              ? "Der ursprüngliche Beleg und seine PDF-Version bleiben unverändert erhalten."
              : payment
                ? "Der vollständige Zahlungseingang ist nachvollziehbar verbucht."
                : "Im PoC wird ausschließlich der exakte vollständige Rechnungsbetrag verbucht."}
          </p>
        </div>
        <span
          className="invoice-settlement__status"
          data-status={
            cancellation ? "cancelled" : payment ? "paid" : "outstanding"
          }
        >
          {cancellation ? "Storniert" : payment ? "Erledigt" : "Offen"}
        </span>
      </header>

      {payment ? (
        <dl className="invoice-settlement__facts" data-testid="payment-record">
          <div>
            <dt>Betrag</dt>
            <dd>{formatMoney(payment.amountMinor, payment.currency)}</dd>
          </div>
          <div>
            <dt>Eingegangen</dt>
            <dd>{formatDate(payment.receivedOn)}</dd>
          </div>
          <div>
            <dt>Referenz</dt>
            <dd>{payment.reference}</dd>
          </div>
          <div>
            <dt>Verbucht</dt>
            <dd>
              {payment.recordedByDisplayName ?? "Berechtigte Finanzrolle"},{" "}
              {formatDateTime(payment.recordedAt)}
            </dd>
          </div>
        </dl>
      ) : null}

      {cancellation ? (
        <div
          className="invoice-settlement__cancellation"
          data-testid="invoice-cancellation"
        >
          <span>Begründung</span>
          <strong>{cancellation.reason}</strong>
          <p>
            Storniert von{" "}
            {cancellation.requestedByDisplayName ?? "berechtigter Rolle"} am{" "}
            {formatDateTime(cancellation.requestedAt)}. Eine Korrektur wird als
            neuer, separat nummerierter Vorgang angelegt.
          </p>
        </div>
      ) : null}

      {canManage && !payment && !cancellation && mode !== "payment" ? (
        <Button
          data-testid="open-payment-form"
          disabled={busy}
          icon={
            <HugeiconsIcon
              icon={AddMoneyCircleIcon}
              size={18}
              strokeWidth={1.8}
            />
          }
          onClick={() => chooseMode("payment")}
          variant="primary"
        >
          Zahlung erfassen
        </Button>
      ) : null}

      {mode === "payment" && !payment && !cancellation ? (
        <form
          className="invoice-settlement__form"
          data-testid="payment-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (amountMatches && reference.trim()) paymentMutation.mutate();
          }}
        >
          <div className="invoice-settlement__form-intro">
            <strong>Vollzahlung verbuchen</strong>
            <p>
              Gleiche Datum, Betrag und Referenz mit dem Bankumsatz ab. Eine
              Teil- oder Überzahlung wird nicht gespeichert.
            </p>
          </div>
          <label>
            <span>Zahlungsbetrag</span>
            <input
              data-testid="payment-amount"
              inputMode="decimal"
              min="0.01"
              onChange={(event) => setAmount(event.target.value)}
              required
              step="0.01"
              type="number"
              value={amount}
            />
            <small>
              Muss exakt {formatMoney(invoice.grossMinor, invoice.currency)}{" "}
              entsprechen.
            </small>
          </label>
          <label>
            <span>Geldeingang am</span>
            <span className="invoice-settlement__input-with-icon">
              <HugeiconsIcon
                aria-hidden="true"
                icon={Calendar03Icon}
                size={17}
                strokeWidth={1.8}
              />
              <input
                data-testid="payment-date"
                max={localIsoDate()}
                min={invoice.issuedAt.slice(0, 10)}
                onChange={(event) => setReceivedOn(event.target.value)}
                required
                type="date"
                value={receivedOn}
              />
            </span>
            <small>Das Buchungsdatum des tatsächlichen Bankumsatzes.</small>
          </label>
          <label className="invoice-settlement__form-wide">
            <span>Zahlungsreferenz</span>
            <input
              data-testid="payment-reference"
              maxLength={160}
              onChange={(event) => setReference(event.target.value)}
              required
              value={reference}
            />
            <small>
              Zum Beispiel Rechnungsnummer oder Verwendungszweck des
              Bankumsatzes.
            </small>
          </label>
          {!amountMatches ? (
            <p className="invoice-settlement__validation" role="alert">
              Der Betrag muss für den PoC exakt dem vollständigen offenen
              Rechnungsbetrag entsprechen.
            </p>
          ) : null}
          <div className="invoice-settlement__form-actions">
            <Button
              disabled={busy}
              onClick={() => setMode(undefined)}
              type="button"
              variant="secondary"
            >
              Abbrechen
            </Button>
            <Button
              data-testid="record-payment"
              disabled={busy || !amountMatches || !reference.trim()}
              type="submit"
              variant="primary"
            >
              {paymentMutation.isPending
                ? "Zahlung wird verbucht …"
                : "Vollzahlung verbuchen"}
            </Button>
          </div>
        </form>
      ) : null}

      {canManage &&
      !cancellation &&
      mode !== "cancellation" &&
      mode !== "payment" ? (
        <Button
          data-testid="open-cancellation-form"
          disabled={busy}
          icon={
            <HugeiconsIcon
              icon={CancelCircleIcon}
              size={18}
              strokeWidth={1.8}
            />
          }
          onClick={() => chooseMode("cancellation")}
          variant="secondary"
        >
          Storno oder Korrektur
        </Button>
      ) : null}

      {mode === "cancellation" && !cancellation ? (
        <form
          className="invoice-settlement__form invoice-settlement__form--danger"
          data-testid="cancellation-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (confirmCancellation && reason.trim().length >= 8) {
              cancellationMutation.mutate();
            }
          }}
        >
          <div className="invoice-settlement__form-intro">
            <strong>Rechnung dauerhaft stornieren</strong>
            <p>
              Nummer, Rechnungsdaten, PDF und eine bereits erfasste Zahlung
              bleiben erhalten. Eine Korrektur erhält später eine neue
              Rechnungsnummer.
            </p>
          </div>
          <label className="invoice-settlement__form-wide">
            <span>Storno- oder Korrekturgrund</span>
            <textarea
              data-testid="cancellation-reason"
              maxLength={500}
              minLength={8}
              onChange={(event) => setReason(event.target.value)}
              required
              rows={3}
              value={reason}
            />
            <small>
              Beschreibe nachvollziehbar, warum der ausgestellte Beleg nicht
              mehr gelten soll.
            </small>
          </label>
          <label className="invoice-settlement__confirmation">
            <input
              checked={confirmCancellation}
              data-testid="confirm-cancellation"
              onChange={(event) => setConfirmCancellation(event.target.checked)}
              type="checkbox"
            />
            <span>
              Ich bestätige das endgültige Storno. Der Beleg kann danach nicht
              wieder geöffnet werden.
            </span>
          </label>
          <div className="invoice-settlement__form-actions">
            <Button
              disabled={busy}
              onClick={() => {
                setMode(undefined);
                setConfirmCancellation(false);
              }}
              type="button"
              variant="secondary"
            >
              Abbrechen
            </Button>
            <Button
              data-testid="cancel-invoice"
              disabled={
                busy || !confirmCancellation || reason.trim().length < 8
              }
              type="submit"
              variant="primary"
            >
              {cancellationMutation.isPending
                ? "Storno wird gespeichert …"
                : "Endgültig stornieren"}
            </Button>
          </div>
        </form>
      ) : null}

      {errorMessage ? (
        <p className="invoice-settlement__error" role="alert">
          {errorMessage}
        </p>
      ) : null}
    </section>
  );
}

function InvoiceLedgerRow({
  canManageDelivery,
  canManageSettlement,
  client,
  documentRecord,
  onChanged,
  record,
}: {
  readonly canManageDelivery: boolean;
  readonly canManageSettlement: boolean;
  readonly client: LeonAidApiClient;
  readonly documentRecord?: GeneratedDocumentRecordResponse;
  readonly onChanged: () => void;
  readonly record: InvoiceRecordResponse;
}) {
  const { invoice } = record;
  return (
    <details
      className="invoice-ledger-row"
      data-invoice-id={invoice.id}
      data-testid="invoice-row"
    >
      <summary>
        <span aria-hidden="true" className="invoice-ledger-row__icon">
          <HugeiconsIcon icon={Invoice03Icon} size={20} strokeWidth={1.8} />
        </span>
        <span className="invoice-ledger-row__identity">
          <strong>{invoice.number}</strong>
          <small>{record.buyerDisplayName}</small>
        </span>
        <span className="invoice-ledger-row__dates">
          <small>Freigegeben {formatDateTime(invoice.issuedAt)}</small>
          <small>Fällig {formatDate(invoice.dueOn)}</small>
          <small data-testid="invoice-open-amount">
            {invoice.status === "cancelled"
              ? "Kein offener Posten · storniert"
              : record.openMinor === 0
                ? "Kein offener Posten · vollständig bezahlt"
                : `${formatMoney(record.openMinor, invoice.currency)} offen`}
          </small>
        </span>
        <span className="invoice-status" data-status={invoice.status}>
          {invoiceStatusLabels[invoice.status]}
        </span>
        <strong className="invoice-ledger-row__amount">
          {formatMoney(invoice.grossMinor, invoice.currency)}
        </strong>
      </summary>
      <div className="invoice-ledger-row__details">
        <InvoiceDocumentPanel
          actionId={invoice.actionId}
          client={client}
          record={documentRecord}
        />
        <InvoiceDeliveryPanel
          canManage={canManageDelivery}
          client={client}
          documentAvailable={documentRecord?.document.status === "available"}
          invoice={record}
          onChanged={onChanged}
        />
        <InvoiceSettlementPanel
          canManage={canManageSettlement}
          client={client}
          onChanged={onChanged}
          record={record}
        />
        <section>
          <span>Unveränderlicher Empfänger</span>
          <strong>{invoice.recipient.recipientName}</strong>
          <address>
            {invoice.recipient.streetLine1}
            <br />
            {invoice.recipient.postalCode} {invoice.recipient.city}
            <br />
            {invoice.recipient.countryCode}
          </address>
        </section>
        <section>
          <span>Rechnungssteller bei Freigabe</span>
          <strong>{invoice.issuer.legalName}</strong>
          <address>
            {invoice.issuer.streetLine1}
            <br />
            {invoice.issuer.postalCode} {invoice.issuer.city}
            <br />
            {invoice.issuer.taxIdentifier}
          </address>
        </section>
        <dl>
          <div>
            <dt>Leistungsdatum</dt>
            <dd>{formatDate(invoice.serviceOn)}</dd>
          </div>
          <div>
            <dt>Zahlungsreferenz</dt>
            <dd>{invoice.paymentReference}</dd>
          </div>
          <div>
            <dt>Netto</dt>
            <dd>{formatMoney(invoice.netMinor, invoice.currency)}</dd>
          </div>
          <div>
            <dt>Steuer</dt>
            <dd>{formatMoney(invoice.taxMinor, invoice.currency)}</dd>
          </div>
        </dl>
        <div className="invoice-ledger-row__lines">
          {invoice.lines.map((line, index) => (
            <div key={`${invoice.id}-${index}`}>
              <span>
                {line.quantity} × {line.description}
              </span>
              <strong>{formatMoney(line.grossMinor, line.currency)}</strong>
            </div>
          ))}
        </div>
        <p className="invoice-ledger-row__tax-note">{invoice.taxNote}</p>
      </div>
    </details>
  );
}

export function InvoiceAdminPage({ client, identity }: InvoiceAdminPageProps) {
  const actions = useMemo(() => {
    const globalFinance =
      identity.globalRoles.includes("finance_reader") ||
      identity.globalRoles.includes("finance_manager");
    const seen = new Set<string>();
    return identity.actionMemberships.filter((membership) => {
      const eligible =
        globalFinance ||
        membership.role === "charity_admin" ||
        membership.role === "finance_reader";
      if (!eligible || seen.has(membership.actionId)) return false;
      seen.add(membership.actionId);
      return true;
    });
  }, [identity.actionMemberships, identity.globalRoles]);
  const [actionId, setActionId] = useState(actions[0]?.actionId ?? "");
  const context = useQuery({
    enabled: Boolean(actionId),
    queryFn: () => client.getInvoiceContext(actionId),
    queryKey: ["invoice-context", actionId],
  });
  const invoices = useQuery({
    enabled: Boolean(actionId),
    queryFn: () => client.listInvoices(actionId),
    queryKey: ["invoices", actionId],
    refetchInterval: (query) =>
      query.state.data?.items.some(({ deliveries }) =>
        deliveries.some(({ status }) =>
          ["queued", "sending", "retrying"].includes(status),
        ),
      )
        ? 750
        : false,
  });
  const documents = useQuery({
    enabled: Boolean(actionId),
    queryFn: () => client.listActionDocuments(actionId),
    queryKey: ["documents", actionId],
    refetchInterval: (query) =>
      query.state.data?.items.some(
        ({ document }) => document.status === "pending",
      )
        ? 750
        : false,
  });
  const documentsByInvoice = useMemo(() => {
    const result = new Map<string, GeneratedDocumentRecordResponse>();
    for (const record of documents.data?.items ?? []) {
      const invoiceId = record.document.invoiceId;
      if (invoiceId && !result.has(invoiceId)) result.set(invoiceId, record);
    }
    return result;
  }, [documents.data?.items]);
  const euroTotal = invoices.data?.currencyTotals.find(
    (item) => item.currency === "EUR",
  );
  const paidCount =
    invoices.data?.items.filter(({ invoice }) => invoice.status === "paid")
      .length ?? 0;

  if (!actions.length) {
    return (
      <div className="invoice-page">
        <header className="invoice-page__header">
          <p className="invoice-eyebrow">ERP Light</p>
          <h1>Rechnungen</h1>
          <p>Freigegebene Rechnungen und ihre unveränderlichen Belegdaten.</p>
        </header>
        <StatusMessage tone="info">
          <strong>Noch keine Charity-Aktion für Finanzen verfügbar</strong>
          <p>
            Sobald du einer Aktion als Charity-Admin oder für Finanzen
            zugeordnet bist, erscheinen ihre Rechnungen hier.
          </p>
        </StatusMessage>
      </div>
    );
  }

  return (
    <div className="invoice-page">
      <header className="invoice-page__header invoice-page__header--split">
        <div>
          <p className="invoice-eyebrow">ERP Light</p>
          <h1>Rechnungen</h1>
          <p>
            Freigegebene Rechnungen mit dauerhaftem Empfänger-, Positions- und
            Rechtstextstand.
          </p>
        </div>
        <div className="invoice-action-picker">
          <label htmlFor="invoice-action">Charity-Aktion</label>
          <select
            data-testid="invoice-action"
            id="invoice-action"
            onChange={(event) => setActionId(event.target.value)}
            value={actionId}
          >
            {actions.map((action) => (
              <option key={action.actionId} value={action.actionId}>
                {action.actionName}
              </option>
            ))}
          </select>
        </div>
      </header>

      {context.isPending || invoices.isPending || documents.isPending ? (
        <div
          aria-label="Rechnungen werden geladen"
          className="invoice-loading"
          role="status"
        >
          <span />
          <span />
          <span />
        </div>
      ) : context.isError || invoices.isError || documents.isError ? (
        <StatusMessage tone="error">
          <strong>Rechnungen nicht erreichbar</strong>
          <p>
            Die Belegdaten konnten gerade nicht geladen werden. Versuche es
            erneut.
          </p>
          <Button
            onClick={() =>
              void Promise.all([
                context.refetch(),
                invoices.refetch(),
                documents.refetch(),
              ])
            }
            variant="secondary"
          >
            Rechnungen neu laden
          </Button>
        </StatusMessage>
      ) : (
        <>
          <section
            className="invoice-profile-bar"
            data-testid="invoice-profile"
          >
            <span aria-hidden="true">
              <HugeiconsIcon
                icon={UserMultiple02Icon}
                size={20}
                strokeWidth={1.8}
              />
            </span>
            <div>
              <small>Rechnungssteller</small>
              <strong>
                {context.data?.profile?.issuer.legalName ??
                  "Rechnungsprofil fehlt"}
              </strong>
              <p>
                {context.data?.profile?.readyToIssue
                  ? `Nächste Nummer: ${context.data.profile.nextInvoiceNumber}`
                  : "Träger, Steuerfall und Nummernkreis müssen bestätigt werden."}
              </p>
            </div>
            <span
              className="invoice-access"
              data-access={
                context.data?.mayIssue || context.data?.mayManageSettlements
                  ? "manage"
                  : "read"
              }
            >
              {context.data?.mayIssue
                ? "Freigabe über Bestellungen"
                : context.data?.mayManageSettlements
                  ? "Finanzbuchung"
                  : "Nur Lesezugriff"}
            </span>
          </section>

          <section
            aria-label="Rechnungskennzahlen"
            className="invoice-totals"
            data-testid="invoice-totals"
          >
            <div>
              <small>Belege</small>
              <strong>{invoices.data?.items.length ?? 0}</strong>
            </div>
            <div>
              <small>Offene Posten</small>
              <strong>
                {euroTotal
                  ? formatMoney(euroTotal.openMinor, euroTotal.currency)
                  : "–"}
              </strong>
            </div>
            <div>
              <small>Vollständig bezahlt</small>
              <strong>{paidCount}</strong>
            </div>
            <div>
              <small>Bruttovolumen aller Belege</small>
              <strong>
                {euroTotal
                  ? formatMoney(euroTotal.grossMinor, euroTotal.currency)
                  : "–"}
              </strong>
            </div>
          </section>

          {invoices.data?.items.length ? (
            <section aria-label="Rechnungsliste" className="invoice-ledger">
              <header>
                <div>
                  <h2>Belegjournal</h2>
                  <p>
                    Öffne einen Beleg, um den bei Freigabe gespeicherten Stand
                    zu sehen.
                  </p>
                </div>
                <span>{invoices.data.items.length} Belege</span>
              </header>
              {invoices.data.items.map((record) => (
                <InvoiceLedgerRow
                  canManageDelivery={Boolean(context.data?.mayIssue)}
                  canManageSettlement={Boolean(
                    context.data?.mayManageSettlements,
                  )}
                  client={client}
                  documentRecord={documentsByInvoice.get(record.invoice.id)}
                  key={record.invoice.id}
                  onChanged={() => {
                    void Promise.all([invoices.refetch(), documents.refetch()]);
                  }}
                  record={record}
                />
              ))}
            </section>
          ) : (
            <div className="invoice-empty">
              <HugeiconsIcon
                aria-hidden="true"
                icon={Invoice03Icon}
                size={26}
                strokeWidth={1.8}
              />
              <strong>Noch keine Rechnung freigegeben</strong>
              <span>
                Prüfbereite Bestellungen können im Bereich „Bestellungen“
                kontrolliert und verbindlich freigegeben werden.
              </span>
              {context.data?.mayIssue ? (
                <a
                  className="ui-button ui-button--secondary"
                  href="/admin/orders"
                >
                  Zu den Bestellungen
                </a>
              ) : null}
            </div>
          )}
        </>
      )}
    </div>
  );
}
