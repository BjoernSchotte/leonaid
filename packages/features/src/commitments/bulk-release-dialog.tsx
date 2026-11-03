import { KeyRound, Receipt } from "lucide-react";
import { useId, useRef, useState } from "react";

import type {
  InvoiceContextResponse,
  InvoiceResponse,
} from "@leonaid/api-client";
import { Button, Icon, Modal, StatusMessage } from "@leonaid/ui";

import {
  releaseSkipLabels,
  runRelease,
  savePendingRelease,
  type ReleaseOutcome,
  type ReleaseRun,
  type ReleaseSelection,
  type ReleaseStop,
} from "./bulk-release";
import {
  berlinDate,
  euro,
  snapshotWindowLabel,
  type OrderRow,
} from "./order-format";

type Phase = "review" | "running" | "done";

export interface BulkReleaseDialogProps {
  readonly actionId: string;
  readonly selection: ReleaseSelection;
  readonly context: InvoiceContextResponse;
  /** Date carried over from a run that stopped for the fresh sign-in. */
  readonly initialServiceOn?: string;
  readonly issue: (
    commitmentId: string,
    serviceOn: string,
  ) => Promise<InvoiceResponse>;
  readonly onClose: () => void;
  /** After every run: refresh the list, tell the person. */
  readonly onFinished: (run: ReleaseRun) => void;
}

const invoiceCount = (count: number) =>
  count === 1 ? "1 Rechnung" : `${count} Rechnungen`;

function freshLogin() {
  const returnTo = encodeURIComponent(
    `${window.location.pathname}${window.location.search}`,
  );
  window.location.assign(`/fresh-login?returnTo=${returnTo}`);
}

/**
 * Review and issue several invoices with one service date. Every order goes
 * through the existing single issue call with its own idempotency key, one
 * after the other, so a retry or a double click never issues twice.
 */
export function BulkReleaseDialog({
  actionId,
  context,
  initialServiceOn,
  issue,
  onClose,
  onFinished,
  selection,
}: BulkReleaseDialogProps) {
  const formId = useId();
  const records = selection.eligible;
  const byId = new Map(records.map((row) => [row.commitment.id, row]));
  const [serviceOn, setServiceOn] = useState(
    initialServiceOn ?? context.endsOn,
  );
  const [phase, setPhase] = useState<Phase>("review");
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [outcomes, setOutcomes] = useState<ReadonlyMap<string, ReleaseOutcome>>(
    new Map(),
  );
  const [stop, setStop] = useState<ReleaseStop | null>(null);
  const running = useRef(false);
  const profile = context.profile;
  const total = records.reduce(
    (sum, row) => sum + row.commitment.totalMinor,
    0,
  );
  const currency = records[0]?.commitment.currency ?? "EUR";

  async function start(ids: readonly string[]) {
    // Guard against a second click before React re-renders the button.
    if (running.current || ids.length === 0) return;
    running.current = true;
    setPhase("running");
    setStop(null);
    setProgress({ done: 0, total: ids.length });
    const previous = outcomes;
    try {
      const run = await runRelease(
        ids,
        (id) => issue(id, serviceOn),
        (done, partial) => {
          setProgress({ done, total: ids.length });
          setOutcomes(new Map([...previous, ...partial]));
        },
      );
      const merged = new Map([...previous, ...run.outcomes]);
      setOutcomes(merged);
      setStop(run.stop);
      if (run.stop?.kind === "fresh-login") {
        // Resume after the sign-in with what is still open.
        savePendingRelease(actionId, {
          ids: ids.filter((id) => merged.get(id)?.kind !== "issued"),
          serviceOn,
        });
        onFinished({ outcomes: merged, stop: run.stop });
        freshLogin();
        return;
      }
      setPhase("done");
      onFinished({ outcomes: merged, stop: run.stop });
    } finally {
      running.current = false;
    }
  }

  const ofKind = (kind: ReleaseOutcome["kind"]) =>
    records.filter((row) => outcomes.get(row.commitment.id)?.kind === kind);
  const retryable = records
    .filter((row) => {
      const kind = outcomes.get(row.commitment.id)?.kind;
      return kind === "unconfirmed" || kind === "not-run";
    })
    .map((row) => row.commitment.id);
  const mayRetry = phase === "done" && stop?.kind !== "forbidden";

  const footer =
    phase === "done" ? (
      <>
        {mayRetry && retryable.length ? (
          <Button
            icon={Receipt}
            onClick={() => void start(retryable)}
            variant="secondary"
          >
            {`${invoiceCount(retryable.length)} erneut senden`}
          </Button>
        ) : null}
        <Button onClick={onClose} variant="primary">
          Schließen
        </Button>
      </>
    ) : (
      <>
        <Button
          disabled={phase === "running"}
          onClick={onClose}
          variant="ghost"
        >
          Abbrechen
        </Button>
        <Button
          data-testid="bulk-release-submit"
          disabled={!profile?.readyToIssue || records.length === 0}
          form={formId}
          icon={KeyRound}
          loading={phase === "running"}
          type="submit"
          variant="primary"
        >
          {phase === "running"
            ? `Wird ausgestellt … ${progress.done}/${progress.total}`
            : `${invoiceCount(records.length)} verbindlich ausstellen`}
        </Button>
      </>
    );

  return (
    <Modal
      className="bulk-release"
      description={
        phase === "done"
          ? undefined
          : `${invoiceCount(records.length)} von ${
              records.length + selection.skipped.length
            } ausgewählten Bestellungen freigebbar.`
      }
      footer={footer}
      onClose={() => {
        // Closing mid-run would hide which orders are already issued.
        if (phase !== "running") onClose();
      }}
      open
      role="dialog"
      size="lg"
      title={
        phase === "done" ? "Ergebnis der Freigabe" : "Rechnungen freigeben"
      }
    >
      <div data-testid="bulk-release">
        {phase === "done" ? (
          <ReleaseResult
            actionId={actionId}
            byId={byId}
            failed={ofKind("failed")}
            issued={ofKind("issued")}
            notRun={ofKind("not-run")}
            outcomes={outcomes}
            selection={selection}
            stop={stop}
            unconfirmed={ofKind("unconfirmed")}
          />
        ) : (
          <form
            className="bulk-release__form"
            id={formId}
            onSubmit={(event) => {
              event.preventDefault();
              void start(records.map((row) => row.commitment.id));
            }}
          >
            {!profile?.readyToIssue ? (
              <StatusMessage tone="error">
                <strong>Rechnungsprofil noch nicht freigegeben.</strong> Träger,
                Steuerfall und Nummernkreis müssen vor der ersten Rechnung
                verbindlich bestätigt sein.
              </StatusMessage>
            ) : null}
            <ReleaseTable currency={currency} records={records} total={total} />
            {selection.skipped.length ? (
              <p className="bulk-release__skipped">
                Nicht dabei:{" "}
                {selection.skipped
                  .map(
                    ({ row, reason }) =>
                      `${row.commitment.buyer.displayName} (${releaseSkipLabels[reason]})`,
                  )
                  .join(", ")}
                .
              </p>
            ) : null}
            <div className="commitment-field">
              <label htmlFor={`${formId}-service-on`}>Leistungsdatum</label>
              <small id={`${formId}-service-help`}>
                Gilt für alle {invoiceCount(records.length)}: der Tag, an dem
                die Leistung für diese Charity-Aktion erbracht wurde.
              </small>
              <input
                aria-describedby={`${formId}-service-help`}
                data-testid="bulk-release-service-on"
                disabled={phase === "running"}
                id={`${formId}-service-on`}
                max={context.endsOn}
                min={context.startsOn}
                name="serviceOn"
                onChange={(event) => setServiceOn(event.target.value)}
                required
                type="date"
                value={serviceOn}
              />
            </div>
            <div className="commitment-invoice-review__warning">
              <strong>Das Ausstellen ist verbindlich.</strong>
              <span>
                Jede Bestellung erhält eine fortlaufende Rechnungsnummer
                {profile ? ` ab ${profile.nextInvoiceNumber}` : ""}. Empfänger,
                Positionen, Preise und Rechtstexte werden unveränderlich
                gespeichert. Korrekturen sind danach nur über Storno möglich.
                Dafür wird Ihre Anmeldung bei Bedarf erneut bestätigt.
              </span>
            </div>
            {phase === "running" ? (
              <p
                aria-live="polite"
                className="bulk-release__progress num"
                role="status"
              >
                {progress.done}/{progress.total} bearbeitet
              </p>
            ) : null}
          </form>
        )}
      </div>
    </Modal>
  );
}

function ReleaseTable({
  currency,
  records,
  total,
}: {
  readonly currency: string;
  readonly records: readonly OrderRow[];
  readonly total: number;
}) {
  return (
    <div
      className="bulk-release__table-wrap"
      role="region"
      aria-label="Rechnungen im Überblick"
      tabIndex={0}
    >
      <table className="bulk-release__table">
        <thead>
          <tr>
            <th scope="col">Besteller</th>
            <th scope="col">Bestellung</th>
            <th scope="col">Positionen</th>
            <th scope="col">Lieferfenster</th>
            <th className="num" scope="col">
              Betrag
            </th>
          </tr>
        </thead>
        <tbody>
          {records.map((row) => {
            const { commitment } = row;
            return (
              <tr data-release-id={commitment.id} key={commitment.id}>
                <th scope="row">{commitment.buyer.displayName}</th>
                <td>
                  <span className="mono">…{commitment.id.slice(-8)}</span> ·{" "}
                  {berlinDate.format(new Date(row.createdAt))}
                </td>
                <td className="num">{commitment.lines.length}</td>
                <td>
                  {commitment.deliveryWindowSnapshot
                    ? snapshotWindowLabel(commitment.deliveryWindowSnapshot)
                    : "–"}
                </td>
                <td className="num">
                  {euro(commitment.totalMinor, commitment.currency)}
                </td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr>
            <th colSpan={4} scope="row">
              Summe
            </th>
            <td className="num" data-testid="bulk-release-total">
              {euro(total, currency)}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

function ReleaseResult({
  actionId,
  byId,
  failed,
  issued,
  notRun,
  outcomes,
  selection,
  stop,
  unconfirmed,
}: {
  readonly actionId: string;
  readonly byId: ReadonlyMap<string, OrderRow>;
  readonly failed: readonly OrderRow[];
  readonly issued: readonly OrderRow[];
  readonly notRun: readonly OrderRow[];
  readonly outcomes: ReadonlyMap<string, ReleaseOutcome>;
  readonly selection: ReleaseSelection;
  readonly stop: ReleaseStop | null;
  readonly unconfirmed: readonly OrderRow[];
}) {
  const name = (row: OrderRow) =>
    byId.get(row.commitment.id)?.commitment.buyer.displayName ?? "";
  const message = (row: OrderRow) => {
    const outcome = outcomes.get(row.commitment.id);
    return outcome && "message" in outcome ? outcome.message : "";
  };
  return (
    <div className="bulk-release__result">
      {stop?.kind === "forbidden" ? (
        <StatusMessage tone="error">
          <strong>Freigabe abgebrochen.</strong> {stop.message}
        </StatusMessage>
      ) : stop?.kind === "network" ? (
        <StatusMessage tone="warning">
          <strong>Verbindung unterbrochen.</strong> Die übrigen Bestellungen
          wurden nicht gesendet. Erneutes Senden ist sicher: bereits
          ausgestellte Rechnungen entstehen nicht doppelt.
        </StatusMessage>
      ) : null}
      <section
        aria-labelledby="bulk-release-issued"
        data-testid="bulk-release-issued"
      >
        <h3 id="bulk-release-issued">
          <Icon icon={Receipt} size={14} /> Ausgestellt ({issued.length})
        </h3>
        {issued.length ? (
          <ul>
            {issued.map((row) => {
              const outcome = outcomes.get(row.commitment.id);
              const invoice =
                outcome?.kind === "issued" ? outcome.invoice : null;
              return (
                <li key={row.commitment.id}>
                  <a
                    className="commitment-link mono"
                    href={`/admin/invoices?action=${encodeURIComponent(actionId)}${
                      invoice ? `&open=${encodeURIComponent(invoice.id)}` : ""
                    }`}
                  >
                    {invoice?.number}
                  </a>{" "}
                  · {name(row)} ·{" "}
                  <span className="num">
                    {invoice
                      ? euro(invoice.grossMinor, invoice.currency)
                      : euro(
                          row.commitment.totalMinor,
                          row.commitment.currency,
                        )}
                  </span>
                  {invoice?.replayed ? (
                    <span className="subtle">
                      {" "}
                      (war bereits ausgestellt, keine zweite Rechnung)
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="subtle">Keine.</p>
        )}
      </section>
      {failed.length ? (
        <section
          aria-labelledby="bulk-release-failed"
          data-testid="bulk-release-failed"
        >
          <h3 id="bulk-release-failed">Fehlgeschlagen ({failed.length})</h3>
          <ul>
            {failed.map((row) => (
              <li key={row.commitment.id}>
                <strong>{name(row)}:</strong> {message(row)}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {unconfirmed.length || notRun.length ? (
        <section
          aria-labelledby="bulk-release-open"
          data-testid="bulk-release-open"
        >
          <h3 id="bulk-release-open">
            Nicht abgeschlossen ({unconfirmed.length + notRun.length})
          </h3>
          <ul>
            {unconfirmed.map((row) => (
              <li key={row.commitment.id}>
                <strong>{name(row)}:</strong> {message(row)}
              </li>
            ))}
            {notRun.map((row) => (
              <li key={row.commitment.id}>
                <strong>{name(row)}:</strong> nicht gesendet.
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {selection.skipped.length ? (
        <section
          aria-labelledby="bulk-release-skipped"
          data-testid="bulk-release-skipped"
        >
          <h3 id="bulk-release-skipped">
            Übersprungen ({selection.skipped.length})
          </h3>
          <ul>
            {selection.skipped.map(({ row, reason }) => (
              <li key={row.commitment.id}>
                <strong>{row.commitment.buyer.displayName}:</strong>{" "}
                {releaseSkipLabels[reason]}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
