import type {
  GeneratedDocumentRecordResponse,
  InvoiceDeliveryResponse,
  InvoicePaymentResponse,
  InvoiceRecordResponse,
} from "@leonaid/api-client";

import { localIsoDate } from "./invoice-format";

/**
 * List status of an invoice. The server settlement stays the source of
 * truth; "overdue" is an invoice with a remainder past its due day (Berlin),
 * so an overdue partial payment shows as overdue.
 */
export type InvoiceListStatus =
  | "open"
  | "partial"
  | "overdue"
  | "paid"
  | "overpaid"
  | "cancelled";

export const invoiceStatusLabels: Readonly<Record<InvoiceListStatus, string>> =
  {
    open: "Offen",
    partial: "Teilweise bezahlt",
    overdue: "Überfällig",
    paid: "Bezahlt",
    overpaid: "Überzahlt",
    cancelled: "Storniert",
  };

export const INVOICE_STATUSES: readonly InvoiceListStatus[] = [
  "open",
  "partial",
  "overdue",
  "paid",
  "overpaid",
  "cancelled",
];

export type SettlementStatus = NonNullable<
  InvoiceRecordResponse["settlementStatus"]
>;

/** Sum of the payment entries of one invoice, in cents. */
export interface InvoiceSettlement {
  readonly status: SettlementStatus;
  readonly paidMinor: number;
  readonly openMinor: number;
  readonly overpaidMinor: number;
  /** Every entry, reversed ones included, oldest first. */
  readonly payments: readonly InvoicePaymentResponse[];
  /** Entries that count toward the sum. */
  readonly active: readonly InvoicePaymentResponse[];
  /** Sent back with each command; a stale value is refused (409). */
  readonly version: number;
}

/**
 * The settlement of a record. Falls back to the single `payment` of an
 * older server, which knew only the exact full payment.
 */
export function invoiceSettlement(
  record: InvoiceRecordResponse,
): InvoiceSettlement {
  const payments = record.payments ?? (record.payment ? [record.payment] : []);
  const active = payments.filter((payment) => !payment.reversal);
  const paidMinor =
    record.paidMinor ??
    active.reduce((sum, payment) => sum + payment.amountMinor, 0);
  const cancelled =
    record.invoice.status === "cancelled" || record.cancellation !== null;
  const status: SettlementStatus =
    record.settlementStatus ??
    (cancelled
      ? "cancelled"
      : paidMinor > record.invoice.grossMinor
        ? "overpaid"
        : paidMinor === record.invoice.grossMinor ||
            record.invoice.status === "paid"
          ? "paid"
          : paidMinor === 0
            ? "open"
            : "partially_paid");
  return {
    status,
    paidMinor,
    openMinor: record.openMinor,
    overpaidMinor:
      record.overpaidMinor ??
      (cancelled ? 0 : Math.max(paidMinor - record.invoice.grossMinor, 0)),
    payments,
    active,
    version:
      record.settlementVersion ??
      payments.reduce((sum, payment) => sum + (payment.reversal ? 2 : 1), 0),
  };
}

/** Dispatch state of the latest e-mail delivery. */
export type InvoiceDispatch = "sent" | "in_progress" | "failed" | "not_sent";

export const invoiceDispatchLabels: Readonly<Record<InvoiceDispatch, string>> =
  {
    sent: "Versendet",
    in_progress: "Wird versendet",
    failed: "Versand fehlgeschlagen",
    not_sent: "Nicht versendet",
  };

export const INVOICE_DISPATCHES: readonly InvoiceDispatch[] = [
  "sent",
  "in_progress",
  "failed",
  "not_sent",
];

export interface InvoiceRow {
  readonly id: string;
  readonly record: InvoiceRecordResponse;
  /** The invoice PDF, when the server returned one. */
  readonly document?: GeneratedDocumentRecordResponse;
  readonly status: InvoiceListStatus;
  readonly dispatch: InvoiceDispatch;
}

export function invoiceListStatus(
  record: InvoiceRecordResponse,
  today: string = localIsoDate(),
): InvoiceListStatus {
  const settlement = invoiceSettlement(record);
  if (settlement.status === "cancelled") return "cancelled";
  if (settlement.status === "overpaid") return "overpaid";
  if (settlement.status === "paid" || record.openMinor === 0) return "paid";
  if (record.invoice.dueOn < today) return "overdue";
  return settlement.status === "partially_paid" ? "partial" : "open";
}

export function invoiceDispatch(
  latest: InvoiceDeliveryResponse | undefined,
): InvoiceDispatch {
  if (!latest) return "not_sent";
  if (latest.status === "sent") return "sent";
  if (latest.status === "failed") return "failed";
  return "in_progress";
}

/** One row per invoice; the newest document of each invoice is attached. */
export function invoiceRows(
  records: readonly InvoiceRecordResponse[],
  documents: readonly GeneratedDocumentRecordResponse[],
  today: string = localIsoDate(),
): InvoiceRow[] {
  const documentsByInvoice = new Map<string, GeneratedDocumentRecordResponse>();
  for (const record of documents) {
    const invoiceId = record.document.invoiceId;
    if (invoiceId && !documentsByInvoice.has(invoiceId)) {
      documentsByInvoice.set(invoiceId, record);
    }
  }
  return records.map((record) => ({
    id: record.invoice.id,
    record,
    document: documentsByInvoice.get(record.invoice.id),
    status: invoiceListStatus(record, today),
    dispatch: invoiceDispatch(record.deliveries[0]),
  }));
}

/**
 * The old `?status=` filter (dashboard links, bookmarks) as a list view id:
 * open, paid and cancelled map to the views of the same name, all to "all".
 */
export function viewForLegacyStatus(status: string | null): string | null {
  if (status === "open") return "open";
  if (status === "paid") return "paid";
  if (status === "cancelled") return "cancelled";
  if (status === "all") return "all";
  return null;
}

/**
 * Rewrites a legacy `?status=` URL to the list view format in place, before
 * the list reads the URL. The first view ("open") is the default and is not
 * written.
 */
export function migrateLegacyStatusParam(
  location: Pick<Location, "pathname" | "search" | "hash"> = window.location,
  history: Pick<History, "replaceState" | "state"> = window.history,
) {
  const params = new URLSearchParams(location.search);
  if (!params.has("status")) return;
  const view = viewForLegacyStatus(params.get("status"));
  params.delete("status");
  if (view && view !== "open" && !params.has("view")) params.set("view", view);
  const search = params.toString();
  history.replaceState(
    history.state,
    "",
    `${location.pathname}${search ? `?${search}` : ""}${location.hash}`,
  );
}

/** Session-scoped idempotency key, so a retried command is not applied twice. */
export function commandKey(storageKey: string, prefix: string) {
  try {
    const stored = window.sessionStorage.getItem(storageKey);
    if (stored) return stored;
    const value = `${prefix}:${crypto.randomUUID()}`;
    window.sessionStorage.setItem(storageKey, value);
    return value;
  } catch {
    return fallbackKeys.get(storageKey) ?? rememberFallback(storageKey, prefix);
  }
}

export function forgetCommandKey(storageKey: string) {
  fallbackKeys.delete(storageKey);
  try {
    window.sessionStorage.removeItem(storageKey);
  } catch {
    // Storage blocked: the in-memory key is gone already.
  }
}

const fallbackKeys = new Map<string, string>();

function rememberFallback(storageKey: string, prefix: string) {
  const value = `${prefix}:${crypto.randomUUID()}`;
  fallbackKeys.set(storageKey, value);
  return value;
}

export const deliveryCommandStorageKey = (invoiceId: string) =>
  `leonaid.invoice-delivery-command.${invoiceId}`;

export const settlementCommandStorageKey = (
  invoiceId: string,
  kind: "cancellation" | "payment",
) => `leonaid.invoice-${kind}-command.${invoiceId}`;

/** The payment form's key, bound to the settlement version it opened with. */
export const paymentCommandStorageKey = (invoiceId: string, version: number) =>
  `${settlementCommandStorageKey(invoiceId, "payment")}.v${version}`;

export const reversalCommandStorageKey = (paymentId: string) =>
  `leonaid.invoice-payment-reversal-command.${paymentId}`;
