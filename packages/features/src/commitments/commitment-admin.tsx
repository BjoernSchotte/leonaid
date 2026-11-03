import { CampaignEditorLink } from "../action-admin/campaign-editor-link";
import {
  requestedUnlistedAction,
  useActionInUrl,
} from "../action-admin/action-location";
import { useContextCommands } from "../command-palette/store";
import {
  DeliveryCompletion,
  deliveryDetailsMissing,
} from "./delivery-completion";
import { normalizeOrdersUrl, setInvoiceSelection } from "./orders-url";

export { legacyOrdersSearch } from "./orders-url";
import { formatQuantities } from "./quantities";

import {
  Calendar,
  CalendarClock,
  CircleDot,
  Flag,
  Globe,
  MapPin,
  Receipt,
  ShoppingBasket,
  Truck,
  UserRound,
} from "lucide-react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import type {
  CommitmentRecordResponse,
  CommitmentResponse,
  CurrentIdentityResponse,
  DeliveryConfigurationResponse,
  InvoiceContextResponse,
  InvoiceResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Avatar,
  Badge,
  Button,
  DetailProps,
  DetailSection,
  DetailTimeline,
  Icon,
  ListView,
  StatusIcon,
  StatusLabel,
  StatusMessage,
  statusShape,
  useOptionalToast,
  type ListColumns,
  type ListProperty,
  type ListSort,
  type ListViewDefinition,
} from "@leonaid/ui";

import { actionErrorMessage } from "../action-admin/errors";

interface CommitmentAdminPageProps {
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
}

type OrderStatus = CommitmentResponse["status"];
type OrderRow = CommitmentRecordResponse;

/** In group order: what needs work first. */
const statusOrder: readonly OrderStatus[] = [
  "review_ready",
  "draft",
  "confirmed",
  "invoiced",
  "cancelled",
];

const statusLabels: Readonly<Record<OrderStatus, string>> = {
  cancelled: "Storniert",
  confirmed: "Bestätigt",
  draft: "Entwurf",
  invoiced: "Fakturiert",
  review_ready: "Prüfbereit",
};

const sourceLabels = {
  acquisition: "Akquise",
  admin: "Verwaltung",
  public_form: "Öffentliches Formular",
} as const;

const NO_WINDOW = "none";
const NO_CAPTURER = "none";

const euro = (amountMinor: number, currency: string) =>
  new Intl.NumberFormat("de-DE", { currency, style: "currency" }).format(
    amountMinor / 100,
  );

const berlinDate = new Intl.DateTimeFormat("de-DE", {
  dateStyle: "medium",
  timeZone: "Europe/Berlin",
});
const berlinDateTime = new Intl.DateTimeFormat("de-DE", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "Europe/Berlin",
});
const shortDay = new Intl.DateTimeFormat("de-DE", {
  day: "2-digit",
  month: "2-digit",
  timeZone: "Europe/Berlin",
});

function lineLabel(commitment: CommitmentResponse) {
  return commitment.lines
    .map((line) => `${line.quantity} × ${line.description}`)
    .join(", ");
}

/** Draft or review-ready orders that still lack invoice or delivery data. */
function detailsMissing(commitment: CommitmentResponse, deliveryOn: boolean) {
  const editable =
    commitment.status === "draft" || commitment.status === "review_ready";
  return (
    editable &&
    (!commitment.invoiceRecipient ||
      deliveryDetailsMissing(commitment, deliveryOn))
  );
}

/* ---------- delivery windows ---------- */

/** "08" for a full hour, "08:30" otherwise (prototype: "07–09 Uhr"). */
function clock(value: string) {
  const time = value.slice(0, 5);
  return time.endsWith(":00") ? time.slice(0, 2) : time;
}

function weekdayDay(isoDay: string) {
  const date = new Date(`${isoDay}T12:00:00Z`);
  const weekday = new Intl.DateTimeFormat("de-DE", {
    weekday: "short",
    timeZone: "UTC",
  })
    .format(date)
    .replace(".", "");
  return `${weekday} ${isoDay.slice(8, 10)}.${isoDay.slice(5, 7)}.`;
}

function configuredWindowLabel(
  window: DeliveryConfigurationResponse["windows"][number],
) {
  return `${weekdayDay(window.deliveryOn)} · ${clock(window.startsAt)}–${clock(window.endsAt)} Uhr`;
}

/** Label from an order's stored window snapshot (the window may be gone). */
function snapshotWindowLabel(snapshot: Record<string, string>) {
  const zone = snapshot.timezone ?? "Europe/Berlin";
  const start = new Date(snapshot.startsAt ?? "");
  const end = new Date(snapshot.endsAt ?? "");
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()))
    return "Lieferfenster";
  const part = (date: Date, options: Intl.DateTimeFormatOptions) =>
    new Intl.DateTimeFormat("de-DE", { ...options, timeZone: zone }).format(
      date,
    );
  const day = part(start, { year: "numeric", month: "2-digit", day: "2-digit" })
    .split(".")
    .reverse()
    .join("-");
  const time = (date: Date) =>
    clock(part(date, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }));
  return `${weekdayDay(day)} · ${time(start)}–${time(end)} Uhr`;
}

interface WindowOption {
  readonly value: string;
  readonly label: string;
  readonly sortKey: string;
}

function windowOptions(
  configuration: DeliveryConfigurationResponse | undefined,
  rows: readonly OrderRow[],
): WindowOption[] {
  const options = new Map<string, WindowOption>();
  for (const window of configuration?.windows ?? [])
    options.set(window.id, {
      value: window.id,
      label: configuredWindowLabel(window),
      sortKey: `${window.deliveryOn}T${window.startsAt}`,
    });
  for (const { commitment } of rows) {
    const id = commitment.deliveryWindowId;
    if (!id || options.has(id)) continue;
    const snapshot = commitment.deliveryWindowSnapshot;
    options.set(id, {
      value: id,
      label: snapshot ? snapshotWindowLabel(snapshot) : "Lieferfenster",
      sortKey: snapshot?.startsAt ?? "~",
    });
  }
  return [...options.values()].sort((a, b) =>
    a.sortKey.localeCompare(b.sortKey),
  );
}

/* ---------- invoice review ---------- */

function invoiceCommandKey(commitmentId: string) {
  const storageKey = `leonaid.invoice-command.${commitmentId}`;
  const existing = window.sessionStorage.getItem(storageKey);
  if (existing) return existing;
  const value = `poc090:${crypto.randomUUID()}`;
  window.sessionStorage.setItem(storageKey, value);
  return value;
}

function InvoiceReview({
  context,
  deliveryMissing,
  error,
  issuing,
  onCancel,
  onIssue,
  record,
}: {
  readonly context: InvoiceContextResponse;
  readonly deliveryMissing: boolean;
  readonly error?: string;
  readonly issuing: boolean;
  readonly onCancel: () => void;
  readonly onIssue: (serviceOn: string) => void;
  readonly record: CommitmentRecordResponse;
}) {
  const { commitment } = record;
  const recipient = commitment.invoiceRecipient;
  const profile = context.profile;
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
    heading.current?.scrollIntoView?.({ block: "nearest" });
  }, []);
  return (
    <section
      aria-labelledby={`invoice-review-${commitment.id}`}
      className="commitment-invoice-review"
      data-testid="invoice-review"
    >
      <header>
        <div>
          <p className="commitment-invoice-review__eyebrow">
            Verbindliche Freigabe
          </p>
          <h3
            id={`invoice-review-${commitment.id}`}
            ref={heading}
            tabIndex={-1}
          >
            Rechnung prüfen
          </h3>
        </div>
        <strong className="commitment-invoice-review__number mono">
          {profile?.nextInvoiceNumber ?? "Nummernkreis fehlt"}
        </strong>
      </header>
      <p className="commitment-invoice-review__intro">
        Kontrollieren Sie die Angaben jetzt. Nach der Freigabe bleiben
        Empfänger, Positionen, Preise und Rechtstexte unverändert gespeichert.
      </p>

      {!profile?.readyToIssue ? (
        <StatusMessage tone="error">
          <strong>Rechnungsprofil noch nicht freigegeben</strong>
          <p>
            Träger, Steuerfall und Nummernkreis müssen vor der ersten Rechnung
            verbindlich bestätigt sein.
          </p>
        </StatusMessage>
      ) : null}

      {deliveryMissing ? (
        <StatusMessage tone="error">
          <strong>Lieferangaben fehlen</strong>
          <p>
            Ergänzen Sie vor der Freigabe Lieferadresse und Lieferfenster unter
            „Angaben ergänzen“.
          </p>
        </StatusMessage>
      ) : null}

      <DetailProps
        items={[
          {
            label: "Rechnungsempfänger",
            value: (
              <span className="commitment-address">
                <strong>
                  {recipient?.recipientName ?? commitment.buyer.displayName}
                </strong>
                {recipient ? (
                  <span>
                    {recipient.streetLine1}, {recipient.postalCode}{" "}
                    {recipient.city}, {recipient.countryCode}
                  </span>
                ) : (
                  <span className="subtle">
                    Für diese Bestellung fehlt eine Rechnungsadresse.
                  </span>
                )}
              </span>
            ),
          },
          {
            label: "Rechnungssteller",
            value: (
              <span className="commitment-address">
                <strong>
                  {profile?.issuer.legalName ?? "Noch nicht hinterlegt"}
                </strong>
                {profile ? (
                  <span>
                    {profile.issuer.streetLine1}, {profile.issuer.postalCode}{" "}
                    {profile.issuer.city} · {profile.issuer.taxIdentifier}
                  </span>
                ) : null}
              </span>
            ),
          },
        ]}
      />

      <div className="commitment-invoice-review__lines">
        {commitment.lines.map((line) => (
          <div key={line.id}>
            <span>
              {line.quantity} × {line.description}
            </span>
            <strong className="num">
              {euro(line.lineTotalMinor, line.currency)}
            </strong>
          </div>
        ))}
        <div className="commitment-invoice-review__total">
          <span>Rechnungsbetrag</span>
          <strong className="num">
            {euro(commitment.totalMinor, commitment.currency)}
          </strong>
        </div>
      </div>

      {profile ? (
        <div className="commitment-invoice-review__legal">
          <span>Steuerhinweis</span>
          <p>{profile.taxNote}</p>
        </div>
      ) : null}

      <form
        className="commitment-invoice-review__approval"
        onSubmit={(event) => {
          event.preventDefault();
          const values = new FormData(event.currentTarget);
          onIssue(String(values.get("serviceOn") ?? ""));
        }}
      >
        <div className="commitment-field">
          <label htmlFor={`invoice-service-on-${commitment.id}`}>
            Leistungsdatum
          </label>
          <small id={`invoice-service-help-${commitment.id}`}>
            Tag, an dem die Leistung für diese Charity-Aktion erbracht wurde.
          </small>
          <div className="commitment-invoice-review__date">
            <Icon icon={Calendar} />
            <input
              aria-describedby={`invoice-service-help-${commitment.id}`}
              data-testid="invoice-service-on"
              defaultValue={context.endsOn}
              id={`invoice-service-on-${commitment.id}`}
              max={context.endsOn}
              min={context.startsOn}
              name="serviceOn"
              required
              type="date"
            />
          </div>
        </div>
        <div className="commitment-invoice-review__warning">
          <strong>Danach ist die Rechnung verbindlich.</strong>
          <span>
            Sie erhält dauerhaft die Nummer {profile?.nextInvoiceNumber ?? "–"}.
            Änderungen erfolgen später nur über Storno oder Korrektur.
          </span>
        </div>
        {error ? <StatusMessage tone="error">{error}</StatusMessage> : null}
        <div className="commitment-invoice-review__actions">
          <Button
            data-testid="issue-invoice"
            disabled={
              issuing || !profile?.readyToIssue || !recipient || deliveryMissing
            }
            icon={Receipt}
            loading={issuing}
            type="submit"
            variant="primary"
          >
            {issuing
              ? "Rechnung wird freigegeben …"
              : "Rechnung verbindlich freigeben"}
          </Button>
          <Button disabled={issuing} onClick={onCancel} variant="ghost">
            Prüfung schließen
          </Button>
        </div>
      </form>
    </section>
  );
}

/* ---------- detail pane ---------- */

interface OrderDetailProps {
  readonly client: LeonAidApiClient;
  readonly record: OrderRow;
  readonly deliveryEnabled: boolean;
  readonly context?: InvoiceContextResponse;
  readonly reviewOpen: boolean;
  readonly issueError?: string;
  readonly issuing: boolean;
  readonly onToggleReview: () => void;
  readonly onIssue: (serviceOn: string) => void;
  readonly onSaved: () => void;
}

function OrderDetail({
  client,
  context,
  deliveryEnabled,
  issueError,
  issuing,
  onIssue,
  onSaved,
  onToggleReview,
  record,
  reviewOpen,
}: OrderDetailProps) {
  const { commitment } = record;
  const editable =
    commitment.status === "draft" || commitment.status === "review_ready";
  const missing = detailsMissing(commitment, deliveryEnabled);
  // The server decides; this only hides a review it would refuse.
  const mayIssue = context?.mayIssue !== false;
  const reviewable = commitment.status === "review_ready" && mayIssue;
  const [editing, setEditing] = useState(false);
  const recipient = commitment.invoiceRecipient;
  const address = commitment.deliveryRecipient;
  const snapshot = commitment.deliveryWindowSnapshot;
  const capturedBy =
    commitment.source === "public_form"
      ? "öffentlichem Formular"
      : (record.capturedByDisplayName ?? sourceLabels[commitment.source]);

  return (
    <div className="commitment-detail" data-commitment-id={commitment.id}>
      {editable && missing ? (
        <div className="next-step">
          <p>
            <strong>Nächster Schritt:</strong> Liefer- und Rechnungsangaben
            ergänzen. Danach ist die Bestellung prüfbereit und die Rechnung kann
            freigegeben werden.
          </p>
          <div className="cluster">
            <Button
              aria-controls={`order-edit-${commitment.id}`}
              aria-expanded={editing}
              data-testid="commitment-edit-details"
              onClick={() => setEditing((open) => !open)}
              variant={editing ? "secondary" : "primary"}
            >
              {editing ? "Eingabe schließen" : "Angaben ergänzen"}
            </Button>
            {reviewable && !reviewOpen ? (
              <Button
                data-testid="review-invoice"
                onClick={onToggleReview}
                variant="ghost"
              >
                Rechnung prüfen
              </Button>
            ) : null}
          </div>
        </div>
      ) : reviewable && !reviewOpen ? (
        <div className="next-step">
          <p>
            <strong>Nächster Schritt:</strong> Rechnung prüfen und verbindlich
            freigeben. Danach ist sie unveränderlich und erhält eine
            fortlaufende Nummer.
          </p>
          <div className="cluster">
            <Button
              data-testid="review-invoice"
              icon={Receipt}
              onClick={onToggleReview}
              variant="primary"
            >
              Rechnung prüfen
            </Button>
            <Button
              aria-controls={`order-edit-${commitment.id}`}
              aria-expanded={editing}
              data-testid="commitment-edit-details"
              onClick={() => setEditing((open) => !open)}
              variant="ghost"
            >
              {editing ? "Eingabe schließen" : "Angaben bearbeiten"}
            </Button>
          </div>
        </div>
      ) : commitment.status === "review_ready" && !mayIssue ? (
        <StatusMessage tone="info">
          Nur lesen. Die Rechnung gibt eine Person frei, die diese Aktion
          verwaltet.
        </StatusMessage>
      ) : null}

      {reviewOpen && context && reviewable ? (
        <InvoiceReview
          context={context}
          deliveryMissing={deliveryDetailsMissing(commitment, deliveryEnabled)}
          error={issueError}
          issuing={issuing}
          onCancel={onToggleReview}
          onIssue={onIssue}
          record={record}
        />
      ) : null}

      {editable && editing ? (
        <div className="pane-section" id={`order-edit-${commitment.id}`}>
          <DeliveryCompletion
            client={client}
            onSaved={onSaved}
            order={commitment}
          />
        </div>
      ) : null}

      <DetailSection title="Bestellung">
        <DetailProps
          items={[
            {
              label: "Status",
              value: <StatusLabel status={statusLabels[commitment.status]} />,
            },
            { label: "Angebot", value: lineLabel(commitment) },
            {
              label: "Menge",
              value: (
                <span className="num">
                  {formatQuantities(
                    commitment.quantities,
                    commitment.totalPieces,
                  )}
                </span>
              ),
            },
            {
              label: "Betrag",
              value: (
                <span className="num">
                  {euro(commitment.totalMinor, commitment.currency)}
                </span>
              ),
            },
            {
              label: "Herkunft",
              value:
                commitment.source === "public_form" ? (
                  <Badge icon={Globe} tone="info">
                    Öffentliches Formular
                  </Badge>
                ) : (
                  <Badge icon={UserRound} tone="neutral">
                    {record.capturedByDisplayName
                      ? `${sourceLabels[commitment.source]}: ${record.capturedByDisplayName}`
                      : sourceLabels[commitment.source]}
                  </Badge>
                ),
            },
            {
              label: "Erfasst",
              value: berlinDateTime.format(new Date(record.createdAt)),
            },
            {
              label: "Rechnung",
              value:
                commitment.status === "invoiced" ? (
                  <a className="commitment-link" href="/admin/invoices">
                    Rechnung ansehen
                  </a>
                ) : commitment.status === "cancelled" ? (
                  <a className="commitment-link" href="/admin/invoices">
                    Stornierte Rechnung ansehen
                  </a>
                ) : (
                  "Noch keine"
                ),
            },
          ]}
        />
      </DetailSection>

      <DetailSection title="Rechnung und Lieferung">
        <DetailProps
          items={[
            {
              label: "Rechnung an",
              value: recipient ? (
                <span className="commitment-address">
                  <span>{recipient.recipientName}</span>
                  <span className="subtle">
                    {recipient.streetLine1}, {recipient.postalCode}{" "}
                    {recipient.city}
                  </span>
                </span>
              ) : (
                <span className="subtle">Keine Rechnungsadresse erfasst</span>
              ),
            },
            {
              label: "Lieferadresse",
              value: address ? (
                <span className="cluster">
                  <Icon icon={MapPin} size={12} />
                  <span>
                    {address.recipientName}, {address.streetLine1},{" "}
                    {address.postalCode} {address.city}
                  </span>
                </span>
              ) : (
                <span className="subtle">Keine Lieferadresse erfasst</span>
              ),
            },
            {
              label: "Lieferfenster",
              value: snapshot ? (
                snapshotWindowLabel(snapshot)
              ) : (
                <span className="subtle">Kein Lieferfenster erfasst</span>
              ),
            },
            {
              label: "Kontakt",
              value: commitment.deliveryContact
                ? [
                    commitment.deliveryContact.name ?? "Kein Name angegeben",
                    commitment.deliveryContact.phone,
                  ]
                    .filter(Boolean)
                    .join(" · ")
                : [commitment.buyer.displayName, commitment.buyer.email]
                    .filter(Boolean)
                    .join(" · "),
            },
          ]}
        />
      </DetailSection>

      <DetailSection title="Verlauf">
        <DetailTimeline
          items={[
            {
              id: "created",
              text: `Erfasst von ${capturedBy}`,
              time: berlinDateTime.format(new Date(record.createdAt)),
              dateTime: record.createdAt,
            },
          ]}
        />
      </DetailSection>
    </div>
  );
}

/* ---------- page ---------- */

const sorts: readonly ListSort<OrderRow>[] = [
  {
    id: "new",
    label: "Neueste zuerst",
    compare: (a, b) =>
      b.createdAt.localeCompare(a.createdAt) ||
      b.commitment.id.localeCompare(a.commitment.id),
  },
  {
    id: "amount",
    label: "Betrag",
    compare: (a, b) => b.commitment.totalMinor - a.commitment.totalMinor,
  },
  {
    id: "buyer",
    label: "Besteller A–Z",
    compare: (a, b) =>
      a.commitment.buyer.displayName.localeCompare(
        b.commitment.buyer.displayName,
        "de",
      ),
  },
];

const views: readonly ListViewDefinition[] = [
  {
    id: "todo",
    label: "Zu prüfen",
    filters: [{ prop: "status", values: ["review_ready", "draft"] }],
    groupBy: "status",
    sort: "new",
  },
  { id: "all", label: "Alle", filters: [], groupBy: null, sort: "new" },
  {
    id: "windows",
    label: "Nach Lieferfenster",
    filters: [
      { prop: "status", values: ["review_ready", "confirmed", "invoiced"] },
    ],
    groupBy: "window",
    sort: "buyer",
  },
  {
    id: "public",
    label: "Öffentlich bestellt",
    filters: [{ prop: "source", values: ["public_form"] }],
    groupBy: "status",
    sort: "new",
  },
];

const getId = (row: OrderRow) => row.commitment.id;
const detailTitle = (row: OrderRow) =>
  `${row.commitment.buyer.displayName} · ${berlinDate.format(new Date(row.createdAt))}`;
const searchText = (row: OrderRow) => {
  const { commitment } = row;
  return [
    commitment.buyer.displayName,
    lineLabel(commitment),
    statusLabels[commitment.status],
    commitment.invoiceRecipient?.recipientName,
    commitment.deliveryRecipient?.recipientName,
    commitment.deliveryRecipient?.city,
    row.capturedByDisplayName,
  ]
    .filter(Boolean)
    .join(" ");
};

export function CommitmentAdminPage({
  client,
  identity,
}: CommitmentAdminPageProps) {
  // Map old links (?status=, ?commitment=, ?invoice=) before the list reads
  // the URL. Runs once, synchronously, before the first render.
  useState(normalizeOrdersUrl);
  const toast = useOptionalToast();
  // Mirrors may_manage_action: a system admin manages every action, a
  // charity admin only their own.
  const systemAdmin = identity.globalRoles.includes("system_admin");
  const memberActions = useMemo(() => {
    const seen = new Set<string>();
    return identity.actionMemberships.filter((membership) => {
      const eligible = systemAdmin || membership.role === "charity_admin";
      if (!eligible || seen.has(membership.actionId)) return false;
      seen.add(membership.actionId);
      return true;
    });
  }, [identity.actionMemberships, systemAdmin]);
  // A search hit links to ?action=<id>; keep that action selectable for the
  // whole visit, even after the selector moves to another action.
  const [unlistedActionId] = useState(() =>
    requestedUnlistedAction(memberActions, systemAdmin),
  );
  const unlistedAction = useQuery({
    enabled: Boolean(unlistedActionId),
    queryFn: () => client.getCharityAction(unlistedActionId!),
    queryKey: ["charity-action", unlistedActionId],
  });
  const memberships = useMemo(
    () =>
      unlistedActionId
        ? [
            {
              actionId: unlistedActionId,
              actionName: unlistedAction.data?.name ?? "Charity-Aktion",
            },
            ...memberActions,
          ]
        : memberActions,
    [memberActions, unlistedActionId, unlistedAction.data?.name],
  );
  const [actionId, setActionId] = useState(() => {
    const requested = new URLSearchParams(window.location.search).get("action");
    return (
      memberships.find((item) => item.actionId === requested)?.actionId ??
      memberships[0]?.actionId ??
      ""
    );
  });
  useActionInUrl(actionId);
  const [reviewId, setReviewId] = useState(
    () => new URLSearchParams(window.location.search).get("invoice") ?? "",
  );
  const [issueError, setIssueError] = useState<string>();
  const [issued, setIssued] = useState<InvoiceResponse>();
  const commitments = useQuery({
    enabled: Boolean(actionId),
    queryFn: () => client.listCommitments(actionId),
    queryKey: ["commitments", actionId],
  });
  const deliveryConfiguration = useQuery({
    enabled: Boolean(actionId),
    queryFn: () => client.getDeliveryConfiguration(actionId),
    queryKey: ["delivery-configuration", actionId],
  });
  const invoiceContext = useQuery({
    enabled: Boolean(actionId),
    queryFn: () => client.getInvoiceContext(actionId),
    queryKey: ["invoice-context", actionId],
  });

  const openReview = (id: string) => {
    setReviewId(id);
    setInvoiceSelection(id || undefined);
    setIssueError(undefined);
  };

  const issueInvoice = useMutation({
    mutationFn: ({
      commitmentId,
      serviceOn,
    }: {
      commitmentId: string;
      serviceOn: string;
    }) =>
      client.issueInvoice(
        actionId,
        commitmentId,
        { serviceOn },
        {
          headers: {
            "Idempotency-Key": invoiceCommandKey(commitmentId),
          },
        },
      ),
    onError(cause) {
      setIssueError(actionErrorMessage(cause).message);
    },
    onSuccess(invoice) {
      window.sessionStorage.removeItem(
        `leonaid.invoice-command.${invoice.commitmentId}`,
      );
      setIssued(invoice);
      openReview("");
      toast?.show({
        title: `Rechnung ${invoice.number} freigegeben.`,
        tone: "success",
      });
      void Promise.all([commitments.refetch(), invoiceContext.refetch()]);
    },
  });

  const rows = useMemo(
    () => commitments.data?.items ?? [],
    [commitments.data?.items],
  );
  const deliveryEnabled = Boolean(deliveryConfiguration.data?.enabled);
  const showWindows =
    deliveryEnabled ||
    rows.some((row) => Boolean(row.commitment.deliveryWindowId));
  const windows = useMemo(
    () => windowOptions(deliveryConfiguration.data, rows),
    [deliveryConfiguration.data, rows],
  );
  const capturers = useMemo(
    () =>
      [
        ...new Set(
          rows.flatMap((row) =>
            row.capturedByDisplayName ? [row.capturedByDisplayName] : [],
          ),
        ),
      ].sort((a, b) => a.localeCompare(b, "de")),
    [rows],
  );
  const hasUncaptured = rows.some((row) => !row.capturedByDisplayName);

  // Status, window and capturer change only through the server's commands
  // (delivery completion, invoice issue), so no property has an inline edit.
  const properties = useMemo<ListProperty<OrderRow>[]>(
    () => [
      {
        id: "status",
        label: "Status",
        icon: CircleDot,
        get: (row) => row.commitment.status,
        options: statusOrder.map((status) => ({
          value: status,
          label: statusLabels[status],
          icon: (
            <StatusIcon
              label={statusLabels[status]}
              status={statusShape[statusLabels[status]] ?? "open"}
            />
          ),
        })),
        chip: (row) => (
          <StatusLabel status={statusLabels[row.commitment.status]} />
        ),
      },
      {
        id: "window",
        label: "Lieferfenster",
        icon: CalendarClock,
        get: (row) => row.commitment.deliveryWindowId ?? NO_WINDOW,
        options: [
          ...windows.map(({ label, value }) => ({ label, value })),
          { value: NO_WINDOW, label: "Noch kein Fenster" },
        ],
        optionsPending: deliveryConfiguration.isPending,
        chip: showWindows
          ? (row) => (
              <>
                <Icon icon={Truck} size={12} />
                <span>
                  {windows
                    .find(
                      (window) =>
                        window.value === row.commitment.deliveryWindowId,
                    )
                    ?.label.replace(" Uhr", "") ?? "Kein Fenster"}
                </span>
              </>
            )
          : undefined,
      },
      {
        id: "acquirer",
        label: "Erfasst von",
        icon: UserRound,
        get: (row) => row.capturedByDisplayName ?? NO_CAPTURER,
        options: [
          ...capturers.map((name) => ({
            value: name,
            label: name,
            icon: <Avatar name={name} size="xs" />,
          })),
          ...(hasUncaptured
            ? [{ value: NO_CAPTURER, label: "Ohne Mitglied" }]
            : []),
        ],
        chip: (row) =>
          row.capturedByDisplayName ? (
            <>
              <Avatar
                label={`Erfasst von ${row.capturedByDisplayName}`}
                name={row.capturedByDisplayName}
                size="xs"
              />
              <span className="chip-name">{row.capturedByDisplayName}</span>
            </>
          ) : null,
      },
      {
        id: "source",
        label: "Herkunft",
        icon: Globe,
        get: (row) => row.commitment.source,
        options: [
          { value: "acquisition", label: sourceLabels.acquisition },
          { value: "public_form", label: sourceLabels.public_form },
          { value: "admin", label: sourceLabels.admin },
        ],
      },
    ],
    [
      capturers,
      deliveryConfiguration.isPending,
      hasUncaptured,
      showWindows,
      windows,
    ],
  );

  const columns = useMemo<ListColumns<OrderRow>>(
    () => ({
      leading: (row) =>
        detailsMissing(row.commitment, deliveryEnabled) ? (
          <Icon
            className="flag-high"
            icon={Flag}
            label="Angaben fehlen"
            size={14}
          />
        ) : (
          <span aria-hidden="true" className="flag-space" />
        ),
      primary: (row) => (
        <span data-order-id={row.commitment.id}>
          {row.commitment.buyer.displayName}
        </span>
      ),
      secondary: (row) =>
        [
          lineLabel(row.commitment),
          row.commitment.source === "public_form"
            ? "öffentlich"
            : (row.capturedByDisplayName ??
              sourceLabels[row.commitment.source]),
          shortDay.format(new Date(row.createdAt)),
        ].join(" · "),
      trailing: (row) => (
        <span
          className={
            row.commitment.status === "cancelled" ? "is-struck" : undefined
          }
        >
          {euro(row.commitment.totalMinor, row.commitment.currency)}
        </span>
      ),
    }),
    [deliveryEnabled],
  );

  const euroTotal = commitments.data?.currencyTotals.find(
    (item) => item.currency === "EUR",
  );
  const status = !actionId
    ? "ready"
    : commitments.isPending
      ? "loading"
      : commitments.isError
        ? "error"
        : "ready";

  return (
    <div className="commitment-list" data-zone="orders">
      <ListView<OrderRow>
        beforeList={
          issued ? (
            <StatusMessage className="commitment-issued" tone="success">
              <strong>
                Rechnung {issued.number} ist verbindlich freigegeben.
              </strong>{" "}
              Der Beleg wurde mit unveränderlichen Empfänger-, Positions- und
              Rechtstextdaten gespeichert.{" "}
              <a href="/admin/invoices">Zur Rechnungsübersicht</a>
            </StatusMessage>
          ) : null
        }
        columns={columns}
        detailTitle={detailTitle}
        emptyIcon={ShoppingBasket}
        entityLabel={{ one: "Bestellung", many: "Bestellungen" }}
        getId={getId}
        headerExtra={
          <>
            {commitments.data ? (
              <span
                className="commitment-sum num"
                data-testid="commitment-totals"
                data-total-boxes={commitments.data.totalBoxes}
                data-total-minor={euroTotal?.totalMinor ?? 0}
                data-total-pieces={commitments.data.totalPieces}
              >
                {formatQuantities(
                  commitments.data.quantities,
                  commitments.data.totalPieces,
                )}{" "}
                ·{" "}
                <span data-testid="commitment-total-value">
                  {euroTotal
                    ? euro(euroTotal.totalMinor, euroTotal.currency)
                    : "–"}
                </span>
              </span>
            ) : null}
            {memberships.length ? (
              <label className="select-inline commitment-action-picker">
                <span className="sr-only">Charity-Aktion</span>
                <select
                  data-testid="commitment-admin-action"
                  id="commitment-admin-action"
                  onChange={(event) => {
                    const url = new URL(window.location.href);
                    url.searchParams.delete("open");
                    url.searchParams.delete("invoice");
                    window.history.replaceState(
                      window.history.state,
                      "",
                      `${url.pathname}${url.search}${url.hash}`,
                    );
                    setActionId(event.target.value);
                    setReviewId("");
                    setIssued(undefined);
                    setIssueError(undefined);
                  }}
                  value={actionId}
                >
                  {memberships.map((membership) => (
                    <option
                      key={membership.actionId}
                      value={membership.actionId}
                    >
                      {membership.actionName}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <CampaignEditorLink actionId={actionId} identity={identity} />
          </>
        }
        id="orders"
        key={actionId}
        onOpen={(row) => {
          // A review belongs to the open order; moving on or closing ends it.
          if (reviewId && row?.commitment.id !== reviewId) openReview("");
        }}
        onRetry={() => void commitments.refetch()}
        properties={properties}
        renderDetail={(row) => (
          <OrderDetail
            client={client}
            context={invoiceContext.data}
            deliveryEnabled={deliveryEnabled}
            issueError={reviewId === row.commitment.id ? issueError : undefined}
            issuing={
              issueInvoice.isPending &&
              issueInvoice.variables?.commitmentId === row.commitment.id
            }
            key={row.commitment.id}
            onIssue={(serviceOn) =>
              issueInvoice.mutate({
                commitmentId: row.commitment.id,
                serviceOn,
              })
            }
            onSaved={() => void commitments.refetch()}
            onToggleReview={() =>
              openReview(
                reviewId === row.commitment.id ? "" : row.commitment.id,
              )
            }
            record={row}
            reviewOpen={reviewId === row.commitment.id}
          />
        )}
        rows={rows}
        searchText={searchText}
        sorts={sorts}
        status={status}
        title="Bestellungen"
        useCommands={useContextCommands}
        views={views}
      />
    </div>
  );
}
