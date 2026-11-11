import { useQuery } from "@tanstack/react-query";
import {
  CircleDot,
  FileCheck,
  HandHeart,
  Mail,
  TriangleAlert,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import {
  ApiError,
  type CurrentIdentityResponse,
  type DonationListResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Badge,
  buttonClassName,
  EmptyState,
  fullBleedPage,
  Icon,
  ListView,
  ReadOnlyNotice,
  StatusIcon,
  StatusLabel,
  statusShape,
  type ListColumns,
  type ListProperty,
  type ListSort,
  type ListViewDefinition,
} from "@leonaid/ui";
import { adminHref } from "@leonaid/ui/base-paths";

import {
  requestedUnlistedAction,
  useActionInUrl,
} from "../action-admin/action-location";
import { useContextCommands } from "../command-palette/store";
import {
  formatMoney,
  localIsoDate,
  shortDate,
} from "../invoices/invoice-format";
import {
  INVOICE_DISPATCHES,
  invoiceDispatchLabels,
} from "../invoices/invoice-model";
import { DonationDetail, type DonationCommand } from "./donation-detail";
import {
  CreateDonationDialog,
  DonationCancellationDialog,
  DonationPaymentDialog,
  DonationPaymentWithdrawalDialog,
  DonationReceiptDialog,
  DonationReceiptVoidDialog,
} from "./donation-dialogs";
import {
  DONATION_RECEIPT_STATES,
  DONATION_STATUSES,
  donationInFlight,
  donationReceiptStateLabels,
  donationRows,
  donationStatusLabels,
  isCapabilityDisabled,
  RECEIVING_BODY_MISSING,
  type DonationRow,
  validDonationReceipt,
} from "./donation-model";

interface DonationAdminPageProps {
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
}

interface ActionOption {
  readonly actionId: string;
  readonly actionName: string;
}

function ActionPicker({
  actionId,
  actions,
  onActionChange,
}: {
  readonly actionId: string;
  readonly actions: readonly ActionOption[];
  readonly onActionChange: (actionId: string) => void;
}) {
  return actions.length > 1 ? (
    <label className="inv-action">
      <span className="small">Charity-Aktion</span>
      <select
        className="input select"
        data-testid="donation-action"
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
    <span className="inv-action small" data-testid="donation-action-name">
      {actions[0].actionName}
    </span>
  ) : null;
}

/** "Spenden" (`/admin/donations`): the donations of one action. */
export function DonationAdminPage({
  client,
  identity,
}: DonationAdminPageProps) {
  // The server names the actions of this page: those with the `donations`
  // capability whose finances the account reads (global finance roles: every
  // such action). A system admin reaches an action by its link only.
  const readsEveryAction =
    identity.globalRoles.includes("system_admin") ||
    identity.globalRoles.includes("finance_reader") ||
    identity.globalRoles.includes("finance_manager");
  const memberActions = identity.donationActions;
  // A link may carry ?action=<id> of an action without a membership; keep
  // it selectable for the whole visit.
  const [unlistedActionId] = useState(() =>
    requestedUnlistedAction(memberActions, readsEveryAction),
  );
  const [actionId, setActionId] = useState(() => {
    const requested = new URLSearchParams(window.location.search).get("action");
    return (
      (unlistedActionId && requested === unlistedActionId
        ? unlistedActionId
        : memberActions.find((item) => item.actionId === requested)
            ?.actionId) ??
      memberActions[0]?.actionId ??
      ""
    );
  });
  useActionInUrl(actionId);

  const donations = useQuery({
    enabled: Boolean(actionId),
    queryFn: () => client.listDonations(actionId),
    queryKey: ["donations", actionId],
    refetchInterval: (query) =>
      query.state.data?.items.some(donationInFlight) ? 750 : false,
    // A refusal (capability off, no access) does not change by asking again.
    retry: (failureCount, error) =>
      !(error instanceof ApiError) && failureCount < 2,
  });
  const unlistedName =
    donations.data?.actionId === unlistedActionId
      ? donations.data?.actionName
      : undefined;
  const actions = useMemo<readonly ActionOption[]>(
    () =>
      unlistedActionId
        ? [
            {
              actionId: unlistedActionId,
              actionName: unlistedName ?? "Charity-Aktion",
            },
            ...memberActions,
          ]
        : memberActions,
    [memberActions, unlistedActionId, unlistedName],
  );
  const today = localIsoDate();
  const rows = useMemo(
    () => donationRows(donations.data?.items ?? []),
    [donations.data?.items],
  );
  const refetch = useCallback(() => {
    void donations.refetch();
  }, [donations]);

  if (!actions.length) {
    return (
      <div className="inv-page inv-ledger-page" data-zone="donations">
        <header className="page-header">
          <div className="page-heading">
            <h1>Spenden</h1>
          </div>
        </header>
        <EmptyState
          description="Sobald Sie einer Aktion als Charity-Admin oder für Finanzen zugeordnet sind, erscheinen ihre Spenden hier."
          headingLevel={2}
          icon={HandHeart}
          title="Noch keine Charity-Aktion für Spenden verfügbar"
        />
      </div>
    );
  }

  const picker = (
    <div className="inv-subnav">
      <span className="small muted" data-testid="donation-receiving-body">
        {donations.data?.receivingBodyName
          ? `Empfangende Körperschaft: ${donations.data.receivingBodyName}`
          : ""}
      </span>
      <ActionPicker
        actionId={actionId}
        actions={actions}
        onActionChange={setActionId}
      />
    </div>
  );

  if (donations.isError && isCapabilityDisabled(donations.error)) {
    return (
      <div
        className="inv-page inv-ledger-page"
        data-testid="donation-capability-disabled"
        data-zone="donations"
      >
        {picker}
        <header className="page-header">
          <div className="page-heading">
            <h1>Spenden</h1>
          </div>
        </header>
        <EmptyState
          action={
            <a
              className={buttonClassName({ variant: "secondary" })}
              href={adminHref(`actions/${actionId}`)}
            >
              Zur Aktion
            </a>
          }
          description="Spenden schalten Sie in der Aktion unter „Funktionen“ ein. Sie können auch oben eine andere Aktion wählen."
          headingLevel={2}
          icon={HandHeart}
          title="Für diese Aktion sind Spenden nicht aktiviert."
        />
      </div>
    );
  }

  const status = donations.isPending
    ? "loading"
    : donations.isError
      ? "error"
      : "ready";
  const data = status === "ready" ? donations.data : undefined;

  return (
    <div className="inv-page" data-zone="donations" {...fullBleedPage}>
      <div className="inv-top">
        {picker}
        {data && !data.mayManage ? (
          <ReadOnlyNotice
            className="inv-readonly"
            data-testid="donation-read-only"
          >
            Ihre Rolle zeigt Spenden, Zahlungen, Spendenzusagen und
            Zuwendungsbestätigungen. Spenden und Zahlungen erfasst die
            Aktionsleitung oder „Finanzen verwalten“; sie stellen auch die
            Zuwendungsbestätigungen aus.
          </ReadOnlyNotice>
        ) : null}
        {data && data.receivingBodyName === null ? (
          <div
            className="callout tone-warn inv-readonly"
            data-testid="donation-receiving-body-missing"
            role="status"
          >
            <Icon icon={TriangleAlert} size={16} />
            <span>
              {RECEIVING_BODY_MISSING}{" "}
              <a href={adminHref("legal/donations")}>Zu „Rechtliches“</a>
            </span>
          </div>
        ) : null}
      </div>
      <DonationList
        actionId={actionId}
        client={client}
        key={actionId}
        mayManage={Boolean(data?.mayManage)}
        maySend={Boolean(data?.maySend)}
        onChanged={refetch}
        onRetry={refetch}
        donorSearch={Boolean(data?.donorSearch)}
        receiptNoticeValidUntil={data?.receiptNoticeValidUntil ?? null}
        receiptSigning={data?.receiptSigning ?? null}
        receivingBodyName={data?.receivingBodyName ?? null}
        rows={rows}
        status={status}
        today={today}
        totals={
          data
            ? {
                received: formatMoney(data.receivedTotalMinor, data.currency),
                pledgedOpen: formatMoney(
                  data.pledgedOpenTotalMinor,
                  data.currency,
                ),
              }
            : undefined
        }
      />
    </div>
  );
}

function DonationList({
  actionId,
  client,
  donorSearch,
  mayManage,
  maySend,
  onChanged,
  onRetry,
  receiptNoticeValidUntil,
  receiptSigning,
  receivingBodyName,
  rows,
  status,
  today,
  totals,
}: {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  readonly donorSearch: boolean;
  readonly mayManage: boolean;
  readonly maySend: boolean;
  readonly onChanged: () => void;
  readonly onRetry: () => void;
  readonly receiptNoticeValidUntil: string | null;
  readonly receiptSigning: DonationListResponse["receiptSigning"];
  readonly receivingBodyName: string | null;
  readonly rows: readonly DonationRow[];
  readonly status: "loading" | "error" | "ready";
  readonly today: string;
  readonly totals?: { readonly received: string; readonly pledgedOpen: string };
}) {
  const [creating, setCreating] = useState(false);
  const [dialog, setDialog] = useState<{
    readonly command: DonationCommand;
    readonly donationId: string;
  } | null>(null);
  const dialogDonation = dialog
    ? (rows.find((row) => row.id === dialog.donationId)?.donation ?? null)
    : null;
  const closeDialog = useCallback(() => setDialog(null), []);
  const onCommand = useCallback(
    (command: DonationCommand, row: DonationRow) =>
      setDialog({ command, donationId: row.id }),
    [],
  );
  const openCreate = useCallback(() => setCreating(true), []);
  const closeCreate = useCallback(() => setCreating(false), []);
  // No donation without the receiving body (D-D6): no create command then.
  const mayCreate = mayManage && receivingBodyName !== null;

  // Status, receipt and dispatch are read-only: they change only through
  // the explicit commands in the pane.
  const properties = useMemo<ListProperty<DonationRow>[]>(
    () => [
      {
        id: "status",
        label: "Status",
        icon: CircleDot,
        get: (row) => row.status,
        options: DONATION_STATUSES.map((value) => ({
          value,
          label: donationStatusLabels[value],
          icon: (
            <StatusIcon
              label={donationStatusLabels[value]}
              status={statusShape[donationStatusLabels[value]] ?? "open"}
            />
          ),
        })),
        chip: (row) => (
          <StatusLabel status={donationStatusLabels[row.status]} />
        ),
      },
      {
        id: "receipt",
        label: "Zuwendungsbestätigung",
        icon: FileCheck,
        get: (row) => row.receipt,
        options: DONATION_RECEIPT_STATES.map((value) => ({
          value,
          label: donationReceiptStateLabels[value],
        })),
        groupable: false,
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
        groupable: false,
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

  const sorts = useMemo<ListSort<DonationRow>[]>(
    () => [
      {
        id: "number",
        label: "Nummer",
        compare: (a, b) =>
          b.donation.number.localeCompare(a.donation.number, "de", {
            numeric: true,
          }),
      },
      {
        id: "pledged",
        label: "Zusage",
        compare: (a, b) =>
          b.donation.pledgedAt.localeCompare(a.donation.pledgedAt),
      },
      {
        id: "amount",
        label: "Betrag",
        compare: (a, b) => b.donation.pledgedMinor - a.donation.pledgedMinor,
      },
    ],
    [],
  );

  const views = useMemo<ListViewDefinition[]>(
    () => [
      {
        id: "open",
        label: "Offen",
        filters: [{ prop: "status", values: ["pledged"] }],
        groupBy: null,
        sort: "number",
      },
      {
        // Paid and still without a valid receipt: the receipt is due.
        id: "paid",
        label: "Bezahlt",
        filters: [
          { prop: "status", values: ["paid"] },
          { prop: "receipt", values: ["none"] },
        ],
        groupBy: null,
        sort: "number",
      },
      {
        id: "confirmed",
        label: "Bestätigt",
        filters: [
          { prop: "status", values: ["paid"] },
          { prop: "receipt", values: ["issued"] },
        ],
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

  const columns = useMemo<ListColumns<DonationRow>>(
    () => ({
      primary: (row) => (
        <span data-donation-row={row.id}>
          <span className="mono order-no">{row.donation.number}</span>{" "}
          {row.donation.donor.name}
        </span>
      ),
      secondary: (row) => {
        const { cancellation, currency, payment, pledgedAt } = row.donation;
        if (cancellation) return `storniert · ${cancellation.reason}`;
        if (payment) {
          const receipt = validDonationReceipt(row.donation);
          return `${formatMoney(payment.amountMinor, currency)} eingegangen am ${shortDate(payment.receivedOn, today)}${receipt ? ` · bestätigt ${receipt.number}` : ""}`;
        }
        return `zugesagt am ${shortDate(pledgedAt, today)} · noch nichts eingegangen`;
      },
      trailing: (row) => (
        <span className={row.status === "cancelled" ? "is-struck" : undefined}>
          {formatMoney(row.donation.pledgedMinor, row.donation.currency)}
        </span>
      ),
    }),
    [today],
  );

  const getId = useCallback((row: DonationRow) => row.id, []);
  const searchText = useCallback(
    (row: DonationRow) => `${row.donation.number} ${row.donation.donor.name}`,
    [],
  );
  const detailTitle = useCallback(
    (row: DonationRow) => `${row.donation.number} · ${row.donation.donor.name}`,
    [],
  );

  return (
    <>
      <ListView<DonationRow>
        className="inv-list"
        columns={columns}
        createLabel="Spende erfassen"
        detailTitle={detailTitle}
        emptyIcon={HandHeart}
        entityLabel={{ one: "Spende", many: "Spenden" }}
        getId={getId}
        headerExtra={
          totals ? (
            <>
              <span
                className="inv-open num"
                data-testid="donation-received-total"
              >
                Eingegangen: {totals.received}
              </span>
              <span
                className="inv-open num"
                data-testid="donation-pledged-open-total"
              >
                Zugesagt, noch offen: {totals.pledgedOpen}
              </span>
            </>
          ) : undefined
        }
        id="donations"
        onCreate={mayCreate ? openCreate : undefined}
        onRetry={onRetry}
        properties={properties}
        renderDetail={(row) => (
          <DonationDetail
            client={client}
            key={row.id}
            mayManage={mayManage}
            maySend={maySend}
            onChanged={onChanged}
            onCommand={onCommand}
            receiptNoticeValidUntil={receiptNoticeValidUntil}
            receiptSigning={receiptSigning}
            row={row}
            today={today}
          />
        )}
        rows={rows}
        searchText={searchText}
        sorts={sorts}
        status={status}
        title="Spenden"
        useCommands={useContextCommands}
        views={views}
      />
      {receivingBodyName !== null ? (
        <CreateDonationDialog
          actionId={actionId}
          client={client}
          donorSearch={donorSearch}
          onChanged={onChanged}
          onClose={closeCreate}
          open={creating && mayCreate}
          receivingBodyName={receivingBodyName}
        />
      ) : null}
      <DonationPaymentDialog
        client={client}
        donation={dialog?.command === "payment" ? dialogDonation : null}
        onChanged={onChanged}
        onClose={closeDialog}
      />
      <DonationPaymentWithdrawalDialog
        client={client}
        donation={dialog?.command === "withdrawal" ? dialogDonation : null}
        onChanged={onChanged}
        onClose={closeDialog}
      />
      <DonationCancellationDialog
        client={client}
        donation={dialog?.command === "cancellation" ? dialogDonation : null}
        onChanged={onChanged}
        onClose={closeDialog}
      />
      <DonationReceiptDialog
        client={client}
        donation={dialog?.command === "receipt" ? dialogDonation : null}
        onChanged={onChanged}
        onClose={closeDialog}
        receiptSigning={receiptSigning}
      />
      <DonationReceiptVoidDialog
        client={client}
        donation={dialog?.command === "receipt-void" ? dialogDonation : null}
        onChanged={onChanged}
        onClose={closeDialog}
      />
    </>
  );
}
