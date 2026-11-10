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
import { BulkReleaseDialog } from "./bulk-release-dialog";
import {
  releaseSelection,
  takePendingRelease,
  type IssuedBefore,
  type ReleaseRun,
  type ReleaseSelection,
} from "./bulk-release";
import { normalizeOrdersUrl, setInvoiceSelection } from "./orders-url";
import {
  OrderCancellationDialog,
  takeCancellationDraft,
} from "./order-cancellation";

export { legacyOrdersSearch } from "./orders-url";
export { releaseSelection, runRelease } from "./bulk-release";
import {
  berlinDate,
  berlinDateTime,
  capturedOffline,
  configuredWindowLabel,
  detailsMissing,
  euro,
  lineLabel,
  NO_CAPTURER,
  NO_WINDOW,
  shortDay,
  snapshotWindowLabel,
  sourceLabels,
  statusLabels,
  type OrderRow,
  type OrderStatus,
} from "./order-format";
import { formatQuantities } from "./quantities";

import {
  Ban,
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

import { ApiError } from "@leonaid/api-client";
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
  NextStep,
  ReadOnlyNotice,
  fullBleedPage,
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
import { ADMIN_BASE, adminHref } from "@leonaid/ui/base-paths";

interface CommitmentAdminPageProps {
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
}

/** In group order: what needs work first. */
const statusOrder: readonly OrderStatus[] = [
  "review_ready",
  "draft",
  "confirmed",
  "invoiced",
  "cancelled",
];

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

/*
 * One idempotency key per order until its invoice is confirmed, so a retry
 * after a lost answer replays instead of issuing again. sessionStorage keeps
 * it across reloads; when storage is unavailable it lives in memory for the
 * page (the server still returns an existing invoice for the order).
 */
const memoryCommandKeys = new Map<string, string>();
const commandStorageKey = (commitmentId: string) =>
  `leonaid.invoice-command.${commitmentId}`;

function invoiceCommandKey(commitmentId: string) {
  const remembered = memoryCommandKeys.get(commitmentId);
  if (remembered) return remembered;
  try {
    const stored = window.sessionStorage.getItem(
      commandStorageKey(commitmentId),
    );
    if (stored) return stored;
  } catch {
    // Storage unavailable: fall through to a key held in memory.
  }
  const value = `poc090:${crypto.randomUUID()}`;
  try {
    window.sessionStorage.setItem(commandStorageKey(commitmentId), value);
  } catch {
    memoryCommandKeys.set(commitmentId, value);
  }
  return value;
}

/** The invoice is confirmed: the next issue for this order is a new command. */
function forgetInvoiceCommandKey(commitmentId: string) {
  memoryCommandKeys.delete(commitmentId);
  try {
    window.sessionStorage.removeItem(commandStorageKey(commitmentId));
  } catch {
    // Nothing stored.
  }
}

/**
 * The server refused the key because it was sent before with other data.
 * Keeping it would refuse every later attempt in this tab; a fresh key is
 * safe because the server returns an existing invoice for the order.
 * Lost answers keep their key, so a retry replays.
 */
function forgetConflictingKey(commitmentId: string, cause: unknown) {
  if (cause instanceof ApiError && cause.detail.code === "idempotency_conflict")
    forgetInvoiceCommandKey(commitmentId);
}

/** A hanging request must not keep the bulk dialog locked. */
const BULK_ISSUE_TIMEOUT_MS = 30_000;

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
  /** The signed-in account; a cancellation draft belongs to it. */
  readonly userId: string;
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
  userId,
}: OrderDetailProps) {
  const { commitment, cancellation, invoice } = record;
  // Back from the fresh sign-in: the dialog reopens with what was typed.
  const [cancelling, setCancelling] = useState<
    ReturnType<typeof takeCancellationDraft> | false
  >(() => takeCancellationDraft(commitment.id, userId) ?? false);
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
      {cancellation ? (
        <div className="commitment-stamp-row" data-testid="order-stamp">
          <span className="stamp">Storniert</span>
          <span className="small muted">
            Grund: {cancellation.reason.replace(/[.!?]\s*$/, "")}. Die
            Bestellung bleibt mit allen Angaben erhalten.
          </span>
        </div>
      ) : null}
      {/* While the form is open its "Angaben speichern" is the one primary
          action, so the block steps aside (DESIGN.md: one primary, ghost
          alternatives). */}
      {editing ? null : editable && missing ? (
        <NextStep
          action={
            <Button
              aria-controls={`order-edit-${commitment.id}`}
              aria-expanded={false}
              data-testid="commitment-edit-details"
              onClick={() => setEditing(true)}
              variant="primary"
            >
              Angaben ergänzen
            </Button>
          }
          alternatives={
            reviewable && !reviewOpen ? (
              <Button
                data-testid="review-invoice"
                onClick={onToggleReview}
                variant="ghost"
              >
                Rechnung prüfen
              </Button>
            ) : null
          }
          consequence="Liefer- und Rechnungsangaben ergänzen. Danach ist die Bestellung prüfbereit und die Rechnung kann freigegeben werden."
        />
      ) : reviewable && !reviewOpen ? (
        <NextStep
          action={
            <Button
              data-testid="review-invoice"
              icon={Receipt}
              onClick={onToggleReview}
              variant="primary"
            >
              Rechnung prüfen
            </Button>
          }
          alternatives={
            <Button
              aria-controls={`order-edit-${commitment.id}`}
              aria-expanded={false}
              data-testid="commitment-edit-details"
              onClick={() => setEditing(true)}
              variant="ghost"
            >
              Angaben bearbeiten
            </Button>
          }
          consequence="Rechnung prüfen und verbindlich freigeben. Danach ist sie unveränderlich und erhält eine fortlaufende Nummer."
        />
      ) : commitment.status === "review_ready" && !mayIssue ? (
        <ReadOnlyNotice>
          Die Rechnung gibt eine Person frei, die diese Aktion verwaltet.
        </ReadOnlyNotice>
      ) : null}

      {commitment.status !== "cancelled" && !editing && !reviewOpen ? (
        <div className="cluster">
          <Button
            data-testid="open-order-cancellation"
            icon={Ban}
            onClick={() => setCancelling(null)}
            size="sm"
            variant="ghost"
          >
            Bestellung stornieren
          </Button>
        </div>
      ) : null}
      {cancelling !== false ? (
        <OrderCancellationDialog
          client={client}
          initial={cancelling}
          onChanged={onSaved}
          onClose={() => setCancelling(false)}
          record={record}
          userId={userId}
        />
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
          <div className="pane-section-actions">
            <Button
              aria-controls={`order-edit-${commitment.id}`}
              aria-expanded
              data-testid="commitment-edit-close"
              onClick={() => setEditing(false)}
              size="sm"
              variant="ghost"
            >
              Eingabe schließen
            </Button>
          </div>
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
            // Offline queue (specs/pwa-offline-queue §11.2): a capture that
            // reached Core noticeably later than it was made.
            ...(capturedOffline(record)
              ? [
                  {
                    label: "Erfasst offline",
                    value: `am ${berlinDateTime.format(new Date(record.commitment.capturedAt!))}`,
                  },
                ]
              : []),
            {
              label: "Rechnung",
              value: invoice ? (
                <a
                  className="commitment-link"
                  href={`${ADMIN_BASE}invoices?action=${encodeURIComponent(commitment.actionId)}&view=all&open=${encodeURIComponent(invoice.id)}`}
                >
                  {invoice.status === "cancelled"
                    ? `${invoice.number} · storniert`
                    : invoice.number}
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
                <span className="commitment-inline-icon">
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
              value:
                commitment.deliveryContact?.name ||
                commitment.deliveryContact?.phone
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
            ...(commitment.deliveryContact?.driverNote
              ? [
                  {
                    label: "Hinweis für den Fahrer",
                    value: commitment.deliveryContact.driverNote,
                  },
                ]
              : []),
          ]}
        />
      </DetailSection>

      {cancellation ? (
        <DetailSection title="Storno">
          <div data-testid="order-cancellation">
            <DetailProps
              items={[
                { label: "Grund", value: cancellation.reason },
                ...(cancellation.note
                  ? [
                      {
                        label: "Notiz",
                        value: (
                          <span className="commitment-note">
                            {cancellation.note}
                          </span>
                        ),
                      },
                    ]
                  : []),
                {
                  label: "Storniert",
                  value: `${cancellation.requestedByDisplayName ?? "Aktionsverwaltung"}, ${berlinDateTime.format(new Date(cancellation.requestedAt))}`,
                },
                {
                  label: "Rechnung",
                  value: cancellation.invoiceNumber
                    ? cancellation.invoiceCancellationNumber
                      ? `Rechnung ${cancellation.invoiceNumber} wurde mitstorniert. Stornorechnung ${cancellation.invoiceCancellationNumber} steht bei der Rechnung.`
                      : `Rechnung ${cancellation.invoiceNumber} wurde mitstorniert.`
                    : invoice?.status === "cancelled"
                      ? `Rechnung ${invoice.number} war bereits storniert.`
                      : "Es gab keine Rechnung.",
                },
              ]}
            />
          </div>
        </DetailSection>
      ) : null}

      <DetailSection title="Verlauf">
        <DetailTimeline
          items={[
            {
              id: "created",
              text: `Erfasst von ${capturedBy}`,
              time: berlinDateTime.format(new Date(record.createdAt)),
              dateTime: record.createdAt,
            },
            ...(cancellation
              ? [
                  {
                    id: "cancelled",
                    text: `Storniert von ${cancellation.requestedByDisplayName ?? "der Aktionsverwaltung"}`,
                    time: berlinDateTime.format(
                      new Date(cancellation.requestedAt),
                    ),
                    dateTime: cancellation.requestedAt,
                  },
                ]
              : []),
          ]}
        />
      </DetailSection>
    </div>
  );
}

/* ---------- bulk release ---------- */

/**
 * The bulk bar's "Rechnungen freigeben" button and its palette command. It
 * mounts with the selection, so the command exists only while rows are
 * checked.
 */
function BulkReleaseAction({
  onOpen,
  selection,
}: {
  readonly onOpen: () => void;
  readonly selection: ReleaseSelection;
}) {
  const eligible = selection.eligible.length;
  const checked = eligible + selection.skipped.length;
  const label = `Rechnungen freigeben (${eligible} von ${checked} freigebbar)`;
  useContextCommands(
    eligible
      ? [
          {
            id: "orders:bulk-release",
            label,
            group: "Bestellungen",
            icon: Receipt,
            keywords: ["Rechnung", "ausstellen", "Sammelfreigabe"],
            run: onOpen,
          },
        ]
      : [],
  );
  return (
    <Button
      data-testid="bulk-release-open"
      disabled={eligible === 0}
      icon={Receipt}
      onClick={onOpen}
      size="sm"
      title={
        eligible === 0
          ? "Keine der ausgewählten Bestellungen ist freigebbar."
          : undefined
      }
      variant="secondary"
    >
      Rechnungen freigeben{" "}
      <span className="num">
        ({eligible} von {checked} freigebbar)
      </span>
    </Button>
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
  const [release, setRelease] = useState<{
    readonly selection: ReleaseSelection;
    readonly clear?: () => void;
    readonly serviceOn?: string;
    readonly issuedBefore?: readonly IssuedBefore[];
  } | null>(null);
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
    onError(cause, { commitmentId }) {
      forgetConflictingKey(commitmentId, cause);
      setIssueError(actionErrorMessage(cause).message);
    },
    onSuccess(invoice) {
      forgetInvoiceCommandKey(invoice.commitmentId);
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
  // Bulk release: only where the server lets this account issue invoices.
  const mayRelease = invoiceContext.data?.mayIssue === true;
  const rowsById = useMemo(
    () => new Map(rows.map((row) => [row.commitment.id, row])),
    [rows],
  );
  // A bulk release that stopped for the fresh sign-in resumes here.
  const pendingChecked = useRef(false);
  useEffect(() => {
    if (
      pendingChecked.current ||
      !actionId ||
      !commitments.data ||
      !deliveryConfiguration.data ||
      !invoiceContext.data
    )
      return;
    pendingChecked.current = true;
    const pending = takePendingRelease(actionId);
    if (!pending || !invoiceContext.data.mayIssue) return;
    const pendingRows = pending.ids.flatMap((id) => {
      const row = rowsById.get(id);
      return row ? [row] : [];
    });
    const selection = releaseSelection(pendingRows, deliveryEnabled);
    // Also when nothing is left: the person sees what was issued before.
    if (selection.eligible.length || pending.issued.length)
      setRelease({
        selection,
        serviceOn: pending.serviceOn,
        issuedBefore: pending.issued,
      });
  }, [
    actionId,
    commitments.data,
    deliveryConfiguration.data,
    deliveryEnabled,
    invoiceContext.data,
    rowsById,
  ]);
  const issueOne = async (commitmentId: string, serviceOn: string) => {
    let invoice: InvoiceResponse;
    try {
      invoice = await client.issueInvoice(
        actionId,
        commitmentId,
        { serviceOn },
        {
          headers: { "Idempotency-Key": invoiceCommandKey(commitmentId) },
          // Ends as "unconfirmed", which is safe to send again.
          signal: AbortSignal.timeout(BULK_ISSUE_TIMEOUT_MS),
        },
      );
    } catch (cause) {
      forgetConflictingKey(commitmentId, cause);
      throw cause;
    }
    forgetInvoiceCommandKey(commitmentId);
    return invoice;
  };
  const releaseFinished = (run: ReleaseRun) => {
    const counts = { issued: 0, existing: 0, failed: 0, open: 0 };
    for (const outcome of run.outcomes.values()) {
      if (outcome.kind === "issued") {
        if (outcome.invoice.replayed) counts.existing += 1;
        else counts.issued += 1;
      } else if (outcome.kind === "failed") counts.failed += 1;
      else counts.open += 1;
    }
    void Promise.all([commitments.refetch(), invoiceContext.refetch()]);
    if (run.stop?.kind === "fresh-login") return;
    const details = [
      counts.existing
        ? `${counts.existing} war${counts.existing === 1 ? "" : "en"} bereits ausgestellt`
        : "",
      counts.failed ? `${counts.failed} fehlgeschlagen` : "",
      counts.open ? `${counts.open} nicht abgeschlossen` : "",
    ].filter(Boolean);
    toast?.show({
      title: `${counts.issued === 1 ? "1 Rechnung" : `${counts.issued} Rechnungen`} ausgestellt.`,
      description: details.length ? `${details.join(", ")}.` : undefined,
      tone: counts.failed || counts.open ? "error" : "success",
    });
  };
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
    <div className="commitment-list" data-zone="orders" {...fullBleedPage}>
      <ListView<OrderRow>
        bulkActions={
          mayRelease
            ? (ids, clear) => {
                const selection = releaseSelection(
                  ids.flatMap((id) => {
                    const row = rowsById.get(id);
                    return row ? [row] : [];
                  }),
                  deliveryEnabled,
                );
                return (
                  <BulkReleaseAction
                    onOpen={() => setRelease({ selection, clear })}
                    selection={selection}
                  />
                );
              }
            : undefined
        }
        beforeList={
          issued ? (
            <StatusMessage className="commitment-issued" tone="success">
              <strong>
                Rechnung {issued.number} ist verbindlich freigegeben.
              </strong>{" "}
              Der Beleg wurde mit unveränderlichen Empfänger-, Positions- und
              Rechtstextdaten gespeichert.{" "}
              <a href={adminHref("invoices")}>Zur Rechnungsübersicht</a>
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
                    setRelease(null);
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
            userId={identity.userId}
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
      {release && invoiceContext.data ? (
        <BulkReleaseDialog
          actionId={actionId}
          context={invoiceContext.data}
          initialServiceOn={release.serviceOn}
          issuedBefore={release.issuedBefore}
          issue={issueOne}
          onClose={() => {
            release.clear?.();
            setRelease(null);
          }}
          onFinished={releaseFinished}
          selection={release.selection}
        />
      ) : null}
    </div>
  );
}
