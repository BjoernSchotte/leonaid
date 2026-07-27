import {
  Calendar03Icon,
  Invoice03Icon,
  Package01Icon,
  UserMultiple02Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import type {
  CommitmentRecordResponse,
  CommitmentResponse,
  CurrentIdentityResponse,
  InvoiceContextResponse,
  InvoiceResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

import { actionErrorMessage } from "../action-admin/errors";

interface CommitmentAdminPageProps {
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
}

type CommitmentFilter =
  | "all"
  | "draft"
  | "review_ready"
  | "confirmed"
  | "invoiced"
  | "cancelled";

const statusLabels = {
  cancelled: "Storniert",
  confirmed: "Bestätigt",
  draft: "Entwurf",
  invoiced: "Fakturiert",
  review_ready: "Prüfbereit",
} as const;

const sourceLabels = {
  acquisition: "Akquise",
  admin: "Admin",
  public_form: "Öffentliches Formular",
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
    timeStyle: "short",
    timeZone: "Europe/Berlin",
  }).format(new Date(value));
}

function lineLabel(commitment: CommitmentResponse) {
  return commitment.lines
    .map((line) => `${line.quantity} × ${line.description}`)
    .join(", ");
}

function invoiceCommandKey(commitmentId: string) {
  const storageKey = `leonaid.invoice-command.${commitmentId}`;
  const existing = window.sessionStorage.getItem(storageKey);
  if (existing) return existing;
  const value = `poc090:${crypto.randomUUID()}`;
  window.sessionStorage.setItem(storageKey, value);
  return value;
}

function setInvoiceSelection(commitmentId?: string) {
  const url = new URL(window.location.href);
  if (commitmentId) {
    url.searchParams.set("invoice", commitmentId);
  } else {
    url.searchParams.delete("invoice");
  }
  window.history.replaceState({}, "", `${url.pathname}${url.search}`);
}

function InvoiceReview({
  context,
  error,
  issuing,
  onCancel,
  onIssue,
  record,
}: {
  readonly context: InvoiceContextResponse;
  readonly error?: string;
  readonly issuing: boolean;
  readonly onCancel: () => void;
  readonly onIssue: (serviceOn: string) => void;
  readonly record: CommitmentRecordResponse;
}) {
  const { commitment } = record;
  const recipient = commitment.invoiceRecipient;
  const profile = context.profile;
  return (
    <section
      aria-labelledby={`invoice-review-${commitment.id}`}
      className="commitment-invoice-review"
      data-testid="invoice-review"
    >
      <header>
        <div>
          <p className="commitment-eyebrow">Verbindliche Freigabe</p>
          <h2 id={`invoice-review-${commitment.id}`}>Rechnung prüfen</h2>
          <p>
            Kontrolliere die Angaben jetzt. Nach der Freigabe bleiben Empfänger,
            Positionen, Preise und Rechtstexte unverändert gespeichert.
          </p>
        </div>
        <strong className="commitment-invoice-review__number">
          {profile?.nextInvoiceNumber ?? "Nummernkreis fehlt"}
        </strong>
      </header>

      {!profile?.readyToIssue ? (
        <StatusMessage tone="error">
          <strong>Rechnungsprofil noch nicht freigegeben</strong>
          <p>
            Träger, Steuerfall und Nummernkreis müssen vor der ersten Rechnung
            verbindlich bestätigt sein.
          </p>
        </StatusMessage>
      ) : null}

      <div className="commitment-invoice-review__facts">
        <section>
          <span>Rechnungsempfänger</span>
          <strong>
            {recipient?.recipientName ?? commitment.buyer.displayName}
          </strong>
          {recipient ? (
            <address>
              {recipient.streetLine1}
              <br />
              {recipient.postalCode} {recipient.city}
              <br />
              {recipient.countryCode}
            </address>
          ) : (
            <small>Für diese Bestellung fehlt eine Rechnungsadresse.</small>
          )}
        </section>
        <section>
          <span>Rechnungssteller</span>
          <strong>
            {profile?.issuer.legalName ?? "Noch nicht hinterlegt"}
          </strong>
          {profile ? (
            <address>
              {profile.issuer.streetLine1}
              <br />
              {profile.issuer.postalCode} {profile.issuer.city}
              <br />
              {profile.issuer.taxIdentifier}
            </address>
          ) : null}
        </section>
      </div>

      <div className="commitment-invoice-review__lines">
        {commitment.lines.map((line) => (
          <div key={line.id}>
            <span>
              {line.quantity} × {line.description}
            </span>
            <strong>{formatMoney(line.lineTotalMinor, line.currency)}</strong>
          </div>
        ))}
        <div className="commitment-invoice-review__total">
          <span>Rechnungsbetrag</span>
          <strong>
            {formatMoney(commitment.totalMinor, commitment.currency)}
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
            <HugeiconsIcon
              aria-hidden="true"
              icon={Calendar03Icon}
              size={19}
              strokeWidth={1.8}
            />
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
          <Button disabled={issuing} onClick={onCancel} variant="ghost">
            Prüfung schließen
          </Button>
          <Button
            data-testid="issue-invoice"
            disabled={issuing || !profile?.readyToIssue || !recipient}
            icon={
              <HugeiconsIcon
                aria-hidden="true"
                icon={Invoice03Icon}
                size={18}
                strokeWidth={1.8}
              />
            }
            type="submit"
          >
            {issuing
              ? "Rechnung wird freigegeben …"
              : "Rechnung verbindlich freigeben"}
          </Button>
        </div>
      </form>
    </section>
  );
}

function CommitmentRow({
  context,
  error,
  issuing,
  onIssue,
  onToggleReview,
  record,
  reviewOpen,
}: {
  readonly context?: InvoiceContextResponse;
  readonly error?: string;
  readonly issuing: boolean;
  readonly onIssue: (serviceOn: string) => void;
  readonly onToggleReview: () => void;
  readonly record: CommitmentRecordResponse;
  readonly reviewOpen: boolean;
}) {
  const { commitment } = record;
  return (
    <article
      className="commitment-ledger-row"
      data-commitment-id={commitment.id}
      data-testid="commitment-row"
    >
      <div className="commitment-ledger-row__buyer">
        <span aria-hidden="true">
          <HugeiconsIcon
            icon={UserMultiple02Icon}
            size={20}
            strokeWidth={1.8}
          />
        </span>
        <div>
          <strong>{commitment.buyer.displayName}</strong>
          <small>
            {sourceLabels[commitment.source]} · {formatDate(record.createdAt)}
          </small>
        </div>
      </div>
      <div className="commitment-ledger-row__order">
        <span>Angebot</span>
        <strong>{lineLabel(commitment)}</strong>
        <small>
          Rechnung an{" "}
          {commitment.invoiceRecipient?.recipientName ??
            commitment.buyer.displayName}
        </small>
      </div>
      <div className="commitment-ledger-row__status">
        <span className="commitment-status" data-status={commitment.status}>
          {statusLabels[commitment.status]}
        </span>
        {record.capturedByDisplayName ? (
          <small>Erfasst von {record.capturedByDisplayName}</small>
        ) : null}
      </div>
      <strong className="commitment-ledger-row__amount">
        {formatMoney(commitment.totalMinor, commitment.currency)}
      </strong>
      <div className="commitment-ledger-row__action">
        {commitment.status === "review_ready" ? (
          <Button
            aria-expanded={reviewOpen}
            data-testid="review-invoice"
            onClick={onToggleReview}
            variant={reviewOpen ? "ghost" : "secondary"}
          >
            {reviewOpen ? "Prüfung schließen" : "Rechnung prüfen"}
          </Button>
        ) : commitment.status === "invoiced" ? (
          <a href="/admin/invoices">Rechnung ansehen</a>
        ) : null}
      </div>
      {reviewOpen && context ? (
        <InvoiceReview
          context={context}
          error={error}
          issuing={issuing}
          onCancel={onToggleReview}
          onIssue={onIssue}
          record={record}
        />
      ) : null}
    </article>
  );
}

export function CommitmentAdminPage({
  client,
  identity,
}: CommitmentAdminPageProps) {
  const memberships = useMemo(
    () =>
      identity.actionMemberships.filter(
        (membership) => membership.role === "charity_admin",
      ),
    [identity.actionMemberships],
  );
  const query = new URLSearchParams(window.location.search);
  const requestedAction = query.get("action");
  const requestedStatus = query.get("status");
  const [actionId, setActionId] = useState(
    memberships.find((item) => item.actionId === requestedAction)?.actionId ??
      memberships[0]?.actionId ??
      "",
  );
  const [filter, setFilter] = useState<CommitmentFilter>(
    ["draft", "review_ready", "confirmed", "invoiced", "cancelled"].includes(
      requestedStatus ?? "",
    )
      ? (requestedStatus as CommitmentFilter)
      : "all",
  );
  const [selectedCommitmentId, setSelectedCommitmentId] = useState(
    () => new URLSearchParams(window.location.search).get("invoice") ?? "",
  );
  const [issueError, setIssueError] = useState<string>();
  const [issued, setIssued] = useState<InvoiceResponse>();
  const commitments = useQuery({
    enabled: Boolean(actionId),
    queryFn: () => client.listCommitments(actionId),
    queryKey: ["commitments", actionId],
  });
  const invoiceContext = useQuery({
    enabled: Boolean(actionId),
    queryFn: () => client.getInvoiceContext(actionId),
    queryKey: ["invoice-context", actionId],
  });
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
      setIssueError(undefined);
      setSelectedCommitmentId("");
      setInvoiceSelection();
      void Promise.all([commitments.refetch(), invoiceContext.refetch()]);
    },
  });
  const visible =
    commitments.data?.items.filter(
      (record) => filter === "all" || record.commitment.status === filter,
    ) ?? [];
  const euroTotal = commitments.data?.currencyTotals.find(
    (item) => item.currency === "EUR",
  );

  return (
    <div className="commitment-page commitment-page--admin">
      <header className="commitment-page__header commitment-page__header--admin">
        <div>
          <p className="commitment-eyebrow">Bestellarbeitsvorrat</p>
          <h1>Bestellungen prüfen</h1>
          <p>
            Entwürfe, prüfbereite Eingänge und fakturierte Bestellungen in einer
            belastbaren Sicht.
          </p>
        </div>
        <div className="commitment-field commitment-action-picker">
          <label htmlFor="commitment-admin-action">Charity-Aktion</label>
          <select
            data-testid="commitment-admin-action"
            id="commitment-admin-action"
            onChange={(event) => {
              setActionId(event.target.value);
              setSelectedCommitmentId("");
              setInvoiceSelection();
              setIssued(undefined);
              setIssueError(undefined);
              const url = new URL(window.location.href);
              url.searchParams.set("action", event.target.value);
              window.history.replaceState(
                {},
                "",
                `${url.pathname}${url.search}`,
              );
            }}
            value={actionId}
          >
            {memberships.map((membership) => (
              <option key={membership.actionId} value={membership.actionId}>
                {membership.actionName}
              </option>
            ))}
          </select>
        </div>
      </header>

      {issued ? (
        <StatusMessage tone="success">
          <strong>Rechnung {issued.number} ist verbindlich freigegeben.</strong>
          <p>
            Der Beleg wurde mit unveränderlichen Empfänger-, Positions- und
            Rechtstextdaten gespeichert.{" "}
            <a href="/admin/invoices">Zur Rechnungsübersicht</a>
          </p>
        </StatusMessage>
      ) : null}

      {commitments.isPending ? (
        <div
          aria-label="Bestellungen werden geladen"
          className="commitment-loading"
          role="status"
        >
          <span />
          <span />
          <span />
        </div>
      ) : commitments.isError ? (
        <StatusMessage tone="error">
          <div>
            <strong>Bestellungen nicht erreichbar</strong>
            <p>
              Der Arbeitsvorrat konnte nicht geladen werden. Prüfe deine
              Verbindung und versuche es erneut.
            </p>
            <Button
              onClick={() => void commitments.refetch()}
              variant="secondary"
            >
              Bestellungen neu laden
            </Button>
          </div>
        </StatusMessage>
      ) : (
        <>
          <section
            aria-label="Bestellsummen"
            className="commitment-totals"
            data-total-boxes={commitments.data?.totalBoxes ?? 0}
            data-total-minor={euroTotal?.totalMinor ?? 0}
            data-total-pieces={commitments.data?.totalPieces ?? 0}
            data-testid="commitment-totals"
          >
            <div>
              <span aria-hidden="true">
                <HugeiconsIcon
                  icon={Invoice03Icon}
                  size={20}
                  strokeWidth={1.8}
                />
              </span>
              <p>
                <small>Bestellungen</small>
                <strong>{commitments.data?.items.length ?? 0}</strong>
              </p>
            </div>
            <div>
              <span aria-hidden="true">
                <HugeiconsIcon
                  icon={Package01Icon}
                  size={20}
                  strokeWidth={1.8}
                />
              </span>
              <p>
                <small>Boxen · Stück</small>
                <strong>
                  {commitments.data?.totalBoxes ?? 0} ·{" "}
                  {commitments.data?.totalPieces ?? 0}
                </strong>
              </p>
            </div>
            <div>
              <p>
                <small>Bestellwert</small>
                <strong data-testid="commitment-total-value">
                  {euroTotal
                    ? formatMoney(euroTotal.totalMinor, euroTotal.currency)
                    : "–"}
                </strong>
              </p>
            </div>
          </section>

          <div className="commitment-ledger-toolbar">
            <div
              aria-label="Bestellungen filtern"
              className="commitment-filter"
              role="tablist"
            >
              {(
                [
                  ["all", "Alle"],
                  ["review_ready", "Prüfbereit"],
                  ["draft", "Entwürfe"],
                  ["confirmed", "Bestätigt"],
                  ["invoiced", "Fakturiert"],
                  ["cancelled", "Storniert"],
                ] as const
              ).map(([value, label]) => (
                <button
                  aria-selected={filter === value}
                  key={value}
                  onClick={() => {
                    setFilter(value);
                    const url = new URL(window.location.href);
                    if (value === "all") url.searchParams.delete("status");
                    else url.searchParams.set("status", value);
                    window.history.replaceState(
                      {},
                      "",
                      `${url.pathname}${url.search}`,
                    );
                  }}
                  role="tab"
                  type="button"
                >
                  {label}
                </button>
              ))}
            </div>
            <span aria-live="polite">
              {visible.length}{" "}
              {visible.length === 1 ? "Bestellung" : "Bestellungen"}
            </span>
          </div>

          {visible.length ? (
            <section aria-label="Bestellliste" className="commitment-ledger">
              {visible.map((record) => (
                <CommitmentRow
                  context={invoiceContext.data}
                  error={
                    selectedCommitmentId === record.commitment.id
                      ? issueError
                      : undefined
                  }
                  issuing={
                    issueInvoice.isPending &&
                    selectedCommitmentId === record.commitment.id
                  }
                  key={record.commitment.id}
                  onIssue={(serviceOn) =>
                    issueInvoice.mutate({
                      commitmentId: record.commitment.id,
                      serviceOn,
                    })
                  }
                  onToggleReview={() => {
                    const next =
                      selectedCommitmentId === record.commitment.id
                        ? ""
                        : record.commitment.id;
                    setSelectedCommitmentId(next);
                    setInvoiceSelection(next || undefined);
                    setIssueError(undefined);
                  }}
                  record={record}
                  reviewOpen={
                    selectedCommitmentId === record.commitment.id &&
                    record.commitment.status === "review_ready"
                  }
                />
              ))}
            </section>
          ) : (
            <div className="commitment-empty">
              <HugeiconsIcon
                aria-hidden="true"
                icon={Invoice03Icon}
                size={24}
                strokeWidth={1.8}
              />
              <strong>Keine Bestellungen in dieser Ansicht</strong>
              <span>Wähle einen anderen Statusfilter.</span>
            </div>
          )}
        </>
      )}
    </div>
  );
}
