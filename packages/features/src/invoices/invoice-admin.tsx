import {
  Calendar03Icon,
  Download04Icon,
  FileViewIcon,
  Invoice03Icon,
  Pdf02Icon,
  UserMultiple02Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import {
  ApiError,
  type CurrentIdentityResponse,
  type GeneratedDocumentRecordResponse,
  type InvoiceRecordResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

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

function InvoiceLedgerRow({
  client,
  documentRecord,
  record,
}: {
  readonly client: LeonAidApiClient;
  readonly documentRecord?: GeneratedDocumentRecordResponse;
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
                  client={client}
                  documentRecord={documentsByInvoice.get(record.invoice.id)}
                  key={record.invoice.id}
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
