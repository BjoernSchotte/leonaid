import { useQuery } from "@tanstack/react-query";
import {
  CircleDot,
  FileText,
  Mail,
  ReceiptEuro,
  TriangleAlert,
  Wallet,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import type {
  CurrentIdentityResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Badge,
  EmptyState,
  Icon,
  fullBleedPage,
  ListView,
  StatusIcon,
  StatusLabel,
  statusShape,
  type ListColumns,
  type ListProperty,
  type ListSort,
  type ListViewDefinition,
  ReadOnlyNotice,
} from "@leonaid/ui";

import {
  requestedUnlistedAction,
  useActionInUrl,
} from "../action-admin/action-location";
import { useContextCommands } from "../command-palette/store";
import { CancellationDialog, PaymentDialog } from "./invoice-dialogs";
import { InvoiceDetail, type InvoiceCommand } from "./invoice-detail";
import { PaymentReversalDialog } from "./invoice-payment-reversal";
import {
  formatMoney,
  localIsoDate,
  relativeDay,
  shortDate,
} from "./invoice-format";
import { DocumentsLedger, PaymentsLedger } from "./invoice-ledgers";
import {
  INVOICE_DISPATCHES,
  INVOICE_STATUSES,
  invoiceDispatchLabels,
  invoiceRows,
  invoiceSettlement,
  invoiceStatusLabels,
  migrateLegacyStatusParam,
  type InvoiceRow,
} from "./invoice-model";
import { adminHref } from "@leonaid/ui/base-paths";

interface InvoiceAdminPageProps {
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
}

export type InvoiceSection = "list" | "payments" | "documents";

const sectionPaths: Readonly<Record<InvoiceSection, string>> = {
  list: adminHref("invoices"),
  payments: adminHref("invoices/payments"),
  documents: adminHref("invoices/documents"),
};

/** The finance area of `/admin/invoices[/payments|/documents]`. */
export function invoiceSection(pathname: string): InvoiceSection {
  const path = pathname.replace(/\/+$/, "");
  if (path.endsWith("/invoices/payments")) return "payments";
  if (path.endsWith("/invoices/documents")) return "documents";
  return "list";
}

function sectionHref(section: InvoiceSection, actionId: string) {
  return actionId
    ? `${sectionPaths[section]}?action=${encodeURIComponent(actionId)}`
    : sectionPaths[section];
}

function SubNav({
  actionId,
  actions,
  current,
  onActionChange,
}: {
  readonly actionId: string;
  readonly actions: readonly { actionId: string; actionName: string }[];
  readonly current: InvoiceSection;
  readonly onActionChange: (actionId: string) => void;
}) {
  const links: readonly [InvoiceSection, string][] = [
    ["list", "Rechnungen"],
    ["payments", "Zahlungen"],
    ["documents", "Dokumente"],
  ];
  return (
    <div className="inv-subnav">
      <nav aria-label="Finanzbereiche" className="section-links">
        {links.map(([section, label]) => (
          <a
            aria-current={current === section ? "page" : undefined}
            data-testid={`invoice-section-${section}`}
            href={sectionHref(section, actionId)}
            key={section}
          >
            {label}
          </a>
        ))}
      </nav>
      {actions.length > 1 ? (
        <label className="inv-action">
          <span className="small">Charity-Aktion</span>
          <select
            className="input select"
            data-testid="invoice-action"
            onChange={(event) => onActionChange(event.target.value)}
            value={actionId}
          >
            {actions.map((action) => (
              <option key={action.actionId} value={action.actionId}>
                {action.actionName}
              </option>
            ))}
          </select>
        </label>
      ) : actions[0] ? (
        <span className="inv-action small" data-testid="invoice-action-name">
          {actions[0].actionName}
        </span>
      ) : null}
    </div>
  );
}

export function InvoiceAdminPage({ client, identity }: InvoiceAdminPageProps) {
  const [section] = useState(() => invoiceSection(window.location.pathname));
  // Old `?status=` links become list views before the list reads the URL.
  useState(() => {
    if (section === "list") migrateLegacyStatusParam();
    return null;
  });
  // Mirrors may_read_all_invoices: system admins and global finance roles
  // read the invoices of every action, not only of their memberships.
  const readsEveryAction =
    identity.globalRoles.includes("system_admin") ||
    identity.globalRoles.includes("finance_reader") ||
    identity.globalRoles.includes("finance_manager");
  const memberActions = useMemo(() => {
    const seen = new Set<string>();
    return identity.actionMemberships.filter((membership) => {
      const eligible =
        readsEveryAction ||
        membership.role === "charity_admin" ||
        membership.role === "finance_reader";
      if (!eligible || seen.has(membership.actionId)) return false;
      seen.add(membership.actionId);
      return true;
    });
  }, [identity.actionMemberships, readsEveryAction]);
  // A search hit links to ?action=<id>; keep that action selectable for the
  // whole visit, even after the selector moves to another action.
  const [unlistedActionId] = useState(() =>
    requestedUnlistedAction(memberActions, readsEveryAction),
  );
  const unlistedContext = useQuery({
    enabled: Boolean(unlistedActionId),
    queryFn: () => client.getInvoiceContext(unlistedActionId!),
    queryKey: ["invoice-context", unlistedActionId],
  });
  const actions = useMemo(
    () =>
      unlistedActionId
        ? [
            {
              actionId: unlistedActionId,
              actionName: unlistedContext.data?.actionName ?? "Charity-Aktion",
            },
            ...memberActions,
          ]
        : memberActions,
    [memberActions, unlistedActionId, unlistedContext.data?.actionName],
  );
  const [actionId, setActionId] = useState(() => {
    const requested = new URLSearchParams(window.location.search).get("action");
    return (
      actions.find((item) => item.actionId === requested)?.actionId ??
      actions[0]?.actionId ??
      ""
    );
  });
  useActionInUrl(actionId);

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
  const today = localIsoDate();
  const rows = useMemo(
    () =>
      invoiceRows(
        invoices.data?.items ?? [],
        documents.data?.items ?? [],
        today,
      ),
    [invoices.data?.items, documents.data?.items, today],
  );
  const refetchRecords = useCallback(() => {
    void Promise.all([invoices.refetch(), documents.refetch()]);
  }, [invoices, documents]);
  const retryAll = useCallback(() => {
    void Promise.all([
      context.refetch(),
      invoices.refetch(),
      documents.refetch(),
    ]);
  }, [context, invoices, documents]);
  const status =
    context.isPending || invoices.isPending || documents.isPending
      ? "loading"
      : context.isError || invoices.isError || documents.isError
        ? "error"
        : "ready";

  useContextCommands(
    useMemo(
      () =>
        (
          [
            ["list", "Rechnungen ansehen", ReceiptEuro],
            ["payments", "Zahlungen ansehen", Wallet],
            ["documents", "Dokumente ansehen", FileText],
          ] as const
        )
          .filter(([target]) => target !== section)
          .map(([target, label, icon]) => ({
            id: `invoices:section:${target}`,
            label,
            group: "Rechnungen",
            icon,
            run: () => window.location.assign(sectionHref(target, actionId)),
          })),
      [actionId, section],
    ),
  );

  if (!actions.length) {
    return (
      <div className="inv-page inv-ledger-page" data-zone="invoices">
        <header className="page-header">
          <div className="page-heading">
            <h1>Rechnungen</h1>
          </div>
        </header>
        <EmptyState
          description="Sobald Sie einer Aktion als Charity-Admin oder für Finanzen zugeordnet sind, erscheinen ihre Rechnungen hier."
          headingLevel={2}
          icon={ReceiptEuro}
          title="Noch keine Charity-Aktion für Finanzen verfügbar"
        />
      </div>
    );
  }

  const readOnly =
    status === "ready" &&
    !context.data?.mayIssue &&
    !context.data?.mayManageSettlements;
  const profileIncomplete =
    status === "ready" &&
    Boolean(context.data?.mayIssue) &&
    !context.data?.profile?.readyToIssue;
  const top = (
    <>
      <SubNav
        actionId={actionId}
        actions={actions}
        current={section}
        onActionChange={setActionId}
      />
      {readOnly ? (
        <ReadOnlyNotice
          className="inv-readonly"
          data-testid="invoice-read-only"
        >
          Ihre Rolle zeigt Rechnungen, Zahlungen und PDFs. Zahlungen und Stornos
          erfasst die Aktionsleitung oder „Finanzen verwalten“.
        </ReadOnlyNotice>
      ) : null}
      {profileIncomplete ? (
        <div
          className="callout tone-warn inv-readonly"
          data-testid="invoice-profile-incomplete"
          role="status"
        >
          <Icon icon={TriangleAlert} size={16} />
          <span>
            <strong>Rechnungsprofil unvollständig.</strong> Träger, Steuerfall
            und Nummernkreis müssen bestätigt werden, bevor neue Rechnungen
            ausgestellt werden.
          </span>
        </div>
      ) : null}
    </>
  );

  if (section !== "list") {
    const state = { status, onRetry: retryAll } as const;
    return (
      <div className="inv-page inv-ledger-page" data-zone="invoices">
        {top}
        {section === "payments" ? (
          <PaymentsLedger actionId={actionId} rows={rows} state={state} />
        ) : (
          <DocumentsLedger
            actionId={actionId}
            client={client}
            documents={documents.data?.items ?? []}
            state={state}
          />
        )}
      </div>
    );
  }

  const euroOpen =
    invoices.data?.currencyTotals.find((item) => item.currency === "EUR")
      ?.openMinor ?? 0;

  return (
    <div className="inv-page" data-zone="invoices" {...fullBleedPage}>
      <div className="inv-top">{top}</div>
      <InvoiceList
        canManageDelivery={Boolean(context.data?.mayIssue)}
        canManageSettlement={Boolean(context.data?.mayManageSettlements)}
        client={client}
        key={actionId}
        mayIssue={Boolean(context.data?.mayIssue)}
        onChanged={refetchRecords}
        onRetry={retryAll}
        openTotal={
          status === "ready" ? formatMoney(euroOpen, "EUR") : undefined
        }
        rows={rows}
        status={status}
        today={today}
      />
    </div>
  );
}

function InvoiceList({
  canManageDelivery,
  canManageSettlement,
  client,
  mayIssue,
  onChanged,
  onRetry,
  openTotal,
  rows,
  status,
  today,
}: {
  readonly canManageDelivery: boolean;
  readonly canManageSettlement: boolean;
  readonly client: LeonAidApiClient;
  readonly mayIssue: boolean;
  readonly onChanged: () => void;
  readonly onRetry: () => void;
  readonly openTotal?: string;
  readonly rows: readonly InvoiceRow[];
  readonly status: "loading" | "error" | "ready";
  readonly today: string;
}) {
  const [dialog, setDialog] = useState<{
    readonly command: InvoiceCommand;
    readonly invoiceId: string;
    readonly paymentId?: string;
  } | null>(null);
  const dialogRecord = dialog
    ? (rows.find((row) => row.id === dialog.invoiceId)?.record ?? null)
    : null;
  const closeDialog = useCallback(() => setDialog(null), []);
  const onCommand = useCallback(
    (command: InvoiceCommand, row: InvoiceRow, paymentId?: string) =>
      setDialog({ command, invoiceId: row.id, paymentId }),
    [],
  );

  // Status and dispatch are read-only: no `edit`, so no letter key and no
  // chip menu. They change only through the explicit commands in the pane.
  const properties = useMemo<ListProperty<InvoiceRow>[]>(
    () => [
      {
        id: "status",
        label: "Status",
        icon: CircleDot,
        get: (row) => row.status,
        options: INVOICE_STATUSES.map((value) => ({
          value,
          label: invoiceStatusLabels[value],
          icon: (
            <StatusIcon
              label={invoiceStatusLabels[value]}
              status={statusShape[invoiceStatusLabels[value]] ?? "open"}
            />
          ),
        })),
        chip: (row) => <StatusLabel status={invoiceStatusLabels[row.status]} />,
      },
      {
        id: "sent",
        label: "Versand",
        icon: Mail,
        get: (row) => row.dispatch,
        options: INVOICE_DISPATCHES.map((value) => ({
          value,
          label: invoiceDispatchLabels[value],
        })),
        chip: (row) =>
          row.dispatch === "failed" ? (
            <Badge icon={Mail} tone="danger">
              Versand fehlgeschlagen
            </Badge>
          ) : null,
      },
    ],
    [],
  );

  const sorts = useMemo<ListSort<InvoiceRow>[]>(
    () => [
      {
        id: "due",
        label: "Fälligkeit",
        compare: (a, b) =>
          a.record.invoice.dueOn.localeCompare(b.record.invoice.dueOn),
      },
      {
        id: "number",
        label: "Nummer",
        compare: (a, b) =>
          b.record.invoice.number.localeCompare(a.record.invoice.number, "de", {
            numeric: true,
          }),
      },
      {
        id: "amount",
        label: "Betrag",
        compare: (a, b) =>
          b.record.invoice.grossMinor - a.record.invoice.grossMinor,
      },
    ],
    [],
  );

  const views = useMemo<ListViewDefinition[]>(
    () => [
      {
        id: "open",
        label: "Offen",
        filters: [{ prop: "status", values: ["open", "partial", "overdue"] }],
        groupBy: "status",
        sort: "due",
      },
      {
        id: "overdue",
        label: "Überfällig",
        filters: [{ prop: "status", values: ["overdue"] }],
        groupBy: null,
        sort: "due",
      },
      {
        id: "paid",
        label: "Bezahlt",
        filters: [{ prop: "status", values: ["paid", "overpaid"] }],
        groupBy: null,
        sort: "number",
      },
      {
        id: "cancelled",
        label: "Storniert",
        filters: [{ prop: "status", values: ["cancelled"] }],
        groupBy: null,
        sort: "number",
      },
      {
        id: "all",
        label: "Alle",
        filters: [],
        groupBy: "status",
        sort: "number",
      },
    ],
    [],
  );

  const columns = useMemo<ListColumns<InvoiceRow>>(
    () => ({
      primary: (row) => (
        <span data-invoice-row={row.id}>
          <span className="mono order-no">{row.record.invoice.number}</span>{" "}
          {row.record.buyerDisplayName}
        </span>
      ),
      secondary: (row) => {
        const { invoice, cancellation } = row.record;
        if (cancellation) return `storniert · ${cancellation.reason}`;
        const settlement = invoiceSettlement(row.record);
        const latest = settlement.active.at(-1);
        if (settlement.status === "overpaid") {
          return `überzahlt · ${formatMoney(settlement.overpaidMinor, invoice.currency)} zu viel`;
        }
        if (settlement.status === "paid" && latest) {
          return `bezahlt ${shortDate(latest.receivedOn, today)}`;
        }
        if (settlement.status === "partially_paid") {
          return `${formatMoney(settlement.openMinor, invoice.currency)} offen · fällig ${relativeDay(invoice.dueOn, today)}`;
        }
        return `fällig ${relativeDay(invoice.dueOn, today)}`;
      },
      trailing: (row) => (
        <span className={row.status === "cancelled" ? "is-struck" : undefined}>
          {formatMoney(
            row.record.invoice.grossMinor,
            row.record.invoice.currency,
          )}
        </span>
      ),
    }),
    [today],
  );

  const getId = useCallback((row: InvoiceRow) => row.id, []);
  const searchText = useCallback(
    (row: InvoiceRow) =>
      `${row.record.invoice.number} ${row.record.buyerDisplayName} ${row.record.invoice.recipient.recipientName} ${invoiceStatusLabels[row.status]} ${row.record.invoice.paymentReference}`,
    [],
  );
  const detailTitle = useCallback(
    (row: InvoiceRow) =>
      `${row.record.invoice.number} · ${row.record.buyerDisplayName}`,
    [],
  );

  return (
    <>
      <ListView<InvoiceRow>
        beforeList={
          status === "ready" && rows.length === 0 && mayIssue ? (
            <div className="callout inv-empty-hint">
              <Icon icon={ReceiptEuro} size={16} />
              <span>
                Rechnungen entstehen aus prüfbereiten Bestellungen.{" "}
                <a href={adminHref("orders")}>Zu den Bestellungen</a>
              </span>
            </div>
          ) : undefined
        }
        className="inv-list"
        columns={columns}
        detailTitle={detailTitle}
        emptyIcon={ReceiptEuro}
        entityLabel={{ one: "Rechnung", many: "Rechnungen" }}
        getId={getId}
        headerExtra={
          openTotal ? (
            <span className="inv-open num" data-testid="invoice-open-total">
              Offen: {openTotal}
            </span>
          ) : undefined
        }
        id="invoices"
        onRetry={onRetry}
        properties={properties}
        renderDetail={(row) => (
          <InvoiceDetail
            canManageDelivery={canManageDelivery}
            canManageSettlement={canManageSettlement}
            client={client}
            key={row.id}
            onChanged={onChanged}
            onCommand={onCommand}
            row={row}
            today={today}
          />
        )}
        rows={rows}
        searchText={searchText}
        sorts={sorts}
        status={status}
        title="Rechnungen"
        useCommands={useContextCommands}
        views={views}
      />
      <PaymentDialog
        client={client}
        onChanged={onChanged}
        onClose={closeDialog}
        record={dialog?.command === "payment" ? dialogRecord : null}
      />
      <CancellationDialog
        client={client}
        onChanged={onChanged}
        onClose={closeDialog}
        record={dialog?.command === "cancellation" ? dialogRecord : null}
      />
      <PaymentReversalDialog
        client={client}
        onChanged={onChanged}
        onClose={closeDialog}
        paymentId={dialog?.paymentId ?? null}
        record={dialog?.command === "reversal" ? dialogRecord : null}
      />
    </>
  );
}
