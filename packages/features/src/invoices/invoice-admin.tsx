import {
  Alert02Icon,
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

function InvoiceLedgerRow({
  canManage,
  client,
  documentRecord,
  onChanged,
  record,
}: {
  readonly canManage: boolean;
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
          canManage={canManage}
          client={client}
          documentAvailable={documentRecord?.document.status === "available"}
          invoice={record}
          onChanged={onChanged}
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
  const openCount =
    invoices.data?.items.filter(({ invoice }) =>
      ["issued", "sent"].includes(invoice.status),
    ).length ?? 0;

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
              data-access={context.data?.mayIssue ? "manage" : "read"}
            >
              {context.data?.mayIssue
                ? "Freigabe über Bestellungen"
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
              <small>Offen oder versendet</small>
              <strong>{openCount}</strong>
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
                  canManage={Boolean(context.data?.mayIssue)}
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
