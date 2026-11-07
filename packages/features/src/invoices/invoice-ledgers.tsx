import { Download, Lock, Wallet, FileText } from "lucide-react";
import type { ReactNode } from "react";

import type {
  GeneratedDocumentRecordResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Button,
  EmptyState,
  ErrorState,
  Icon,
  SkeletonRows,
  StatusIcon,
} from "@leonaid/ui";

import {
  formatDateTime,
  formatFileSize,
  formatMoney,
  shortDate,
} from "./invoice-format";
import { useDocumentDownload } from "./invoice-detail";
import { invoiceSettlement, type InvoiceRow } from "./invoice-model";
import { ADMIN_BASE } from "@leonaid/ui/base-paths";

export interface LedgerState {
  readonly status: "loading" | "error" | "ready";
  readonly onRetry: () => void;
}

/** Opens one invoice in the list's pane. */
export function invoiceHref(actionId: string, invoiceId: string) {
  return `${ADMIN_BASE}invoices?action=${encodeURIComponent(actionId)}&open=${encodeURIComponent(invoiceId)}`;
}

function LedgerBody({
  children,
  state,
}: {
  readonly children: ReactNode;
  readonly state: LedgerState;
}) {
  if (state.status === "loading") return <SkeletonRows rows={6} />;
  if (state.status === "error") {
    return (
      <ErrorState
        onRetry={state.onRetry}
        title="Die Liste konnte nicht geladen werden"
      >
        Der Server hat nicht geantwortet. Prüfen Sie die Verbindung und
        versuchen Sie es erneut.
      </ErrorState>
    );
  }
  return <>{children}</>;
}

/** "Zahlungen": every recorded payment, newest first. */
export function PaymentsLedger({
  actionId,
  rows,
  state,
}: {
  readonly actionId: string;
  readonly rows: readonly InvoiceRow[];
  readonly state: LedgerState;
}) {
  // Every entry, newest first. Reversed entries stay visible but do not
  // count toward the number of receipts or the total.
  const entries = rows
    .flatMap((row) =>
      invoiceSettlement(row.record).payments.map((payment) => ({
        payment,
        row,
      })),
    )
    .sort(
      (a, b) =>
        b.payment.receivedOn.localeCompare(a.payment.receivedOn) ||
        b.payment.recordedAt.localeCompare(a.payment.recordedAt),
    );
  const paid = entries.filter(({ payment }) => !payment.reversal);
  const totals = new Map<string, number>();
  for (const { payment } of paid) {
    totals.set(
      payment.currency,
      (totals.get(payment.currency) ?? 0) + payment.amountMinor,
    );
  }
  const totalText = [...totals.entries()]
    .map(([currency, minor]) => formatMoney(minor, currency))
    .join(" · ");

  return (
    <>
      <header className="page-header">
        <div className="page-heading">
          <h1>Zahlungen</h1>
          {state.status === "ready" ? (
            <span className="page-count num" data-testid="payments-count">
              {paid.length} {paid.length === 1 ? "Eingang" : "Eingänge"}
              {totalText ? ` · ${totalText}` : ""}
            </span>
          ) : null}
        </div>
      </header>
      <LedgerBody state={state}>
        {entries.length === 0 ? (
          <EmptyState
            description="Erfasste Zahlungseingänge erscheinen hier mit Datum und Rechnung."
            headingLevel={2}
            icon={Wallet}
            title="Noch keine Zahlungen"
          />
        ) : (
          <div
            aria-label="Erfasste Zahlungen"
            className="table-wrap"
            role="region"
            tabIndex={0}
          >
            <table className="table" data-testid="payments-table">
              <caption className="sr-only">Erfasste Zahlungen</caption>
              <thead>
                <tr>
                  <th scope="col">Eingang</th>
                  <th scope="col">Rechnung</th>
                  <th scope="col">Von</th>
                  <th scope="col">Erfasst von</th>
                  <th className="right" scope="col">
                    Betrag
                  </th>
                </tr>
              </thead>
              <tbody>
                {entries.map(({ payment, row }) => (
                  <tr
                    data-reversed={payment.reversal ? "true" : undefined}
                    key={payment.id}
                  >
                    <td className="num">{shortDate(payment.receivedOn)}</td>
                    <td>
                      <a className="mono" href={invoiceHref(actionId, row.id)}>
                        {row.record.invoice.number}
                      </a>
                    </td>
                    <td>{row.record.buyerDisplayName}</td>
                    <td>
                      {payment.recordedByDisplayName ??
                        "Berechtigte Finanzrolle"}
                    </td>
                    <td className="right num">
                      <span
                        className={payment.reversal ? "is-struck" : undefined}
                      >
                        {formatMoney(payment.amountMinor, payment.currency)}
                      </span>
                      {payment.reversal ? (
                        <span className="small subtle inv-ledger-note">
                          zurückgebucht
                        </span>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </LedgerBody>
    </>
  );
}

/** "Dokumente": every invoice PDF of the action, newest first. */
export function DocumentsLedger({
  actionId,
  client,
  documents,
  state,
}: {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  readonly documents: readonly GeneratedDocumentRecordResponse[];
  readonly state: LedgerState;
}) {
  const shown = [...documents].sort((a, b) =>
    b.document.createdAt.localeCompare(a.document.createdAt),
  );
  return (
    <>
      <header className="page-header">
        <div className="page-heading">
          <h1>Dokumente</h1>
          {state.status === "ready" ? (
            <span className="page-count num" data-testid="documents-count">
              {shown.length} {shown.length === 1 ? "PDF" : "PDFs"}
            </span>
          ) : null}
        </div>
      </header>
      <p className="small muted inv-doc-note">
        <Icon icon={Lock} size={14} /> Ausgestellte PDFs sind unveränderlich.
        Korrekturen entstehen immer als neues Dokument.
      </p>
      <LedgerBody state={state}>
        {shown.length === 0 ? (
          <EmptyState
            description="Das PDF einer Rechnung entsteht beim Ausstellen."
            headingLevel={2}
            icon={FileText}
            title="Noch keine Dokumente"
          />
        ) : (
          <div
            aria-label="Finanzdokumente"
            className="table-wrap"
            role="region"
            tabIndex={0}
          >
            <table className="table" data-testid="documents-table">
              <caption className="sr-only">Finanzdokumente</caption>
              <thead>
                <tr>
                  <th scope="col">Dokument</th>
                  <th scope="col">Art</th>
                  <th scope="col">Erstellt</th>
                  <th className="right" scope="col">
                    Größe
                  </th>
                  <th scope="col">
                    <span className="sr-only">Herunterladen</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {shown.map((record) => (
                  <DocumentRow
                    actionId={actionId}
                    client={client}
                    key={record.document.id}
                    record={record}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </LedgerBody>
    </>
  );
}

function DocumentRow({
  actionId,
  client,
  record,
}: {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  readonly record: GeneratedDocumentRecordResponse;
}) {
  const { document: generated } = record;
  const title = record.invoiceNumber
    ? `Rechnung ${record.invoiceNumber} · ${record.buyerDisplayName}`
    : (generated.filename ?? "Rechnungs-PDF");
  const filename = generated.filename ?? "Rechnung.pdf";
  const { busy, download, errorMessage } = useDocumentDownload(
    client,
    actionId,
    generated.id,
    filename,
  );
  const shape =
    generated.status === "available"
      ? "done"
      : generated.status === "pending"
        ? "progress"
        : "cancelled";
  const stateLabel =
    generated.status === "available"
      ? "Bereit"
      : generated.status === "pending"
        ? "Wird erzeugt"
        : "Entfernt";
  return (
    <tr data-testid="document-row">
      <td>
        <span className="cluster">
          <StatusIcon label={stateLabel} status={shape} />
          {generated.invoiceId ? (
            <a href={invoiceHref(actionId, generated.invoiceId)}>{title}</a>
          ) : (
            title
          )}
        </span>
        {errorMessage ? (
          <span className="inv-error small" role="alert">
            {errorMessage}
          </span>
        ) : null}
      </td>
      <td>Rechnung</td>
      <td className="num">
        <time
          dateTime={generated.createdAt}
          title={formatDateTime(generated.createdAt)}
        >
          {shortDate(generated.createdAt)}
        </time>
      </td>
      <td className="right num">
        {generated.sizeBytes != null
          ? formatFileSize(generated.sizeBytes)
          : "–"}
      </td>
      <td className="right">
        {generated.status === "available" ? (
          <Button
            aria-label={`${title} herunterladen`}
            data-testid="download-document"
            icon={Download}
            loading={busy}
            onClick={() => void download()}
            size="sm"
            variant="ghost"
          >
            PDF
          </Button>
        ) : null}
      </td>
    </tr>
  );
}
