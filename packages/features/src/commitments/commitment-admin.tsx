import {
  Invoice03Icon,
  Package01Icon,
  UserMultiple02Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import type {
  CommitmentRecordResponse,
  CommitmentResponse,
  CurrentIdentityResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

interface CommitmentAdminPageProps {
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
}

type CommitmentFilter = "all" | "review_ready" | "draft";

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

function CommitmentRow({
  record,
}: {
  readonly record: CommitmentRecordResponse;
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
  const [actionId, setActionId] = useState(memberships[0]?.actionId ?? "");
  const [filter, setFilter] = useState<CommitmentFilter>("all");
  const commitments = useQuery({
    enabled: Boolean(actionId),
    queryFn: () => client.listCommitments(actionId),
    queryKey: ["commitments", actionId],
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
            onChange={(event) => setActionId(event.target.value)}
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
                ] as const
              ).map(([value, label]) => (
                <button
                  aria-selected={filter === value}
                  key={value}
                  onClick={() => setFilter(value)}
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
                <CommitmentRow key={record.commitment.id} record={record} />
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
