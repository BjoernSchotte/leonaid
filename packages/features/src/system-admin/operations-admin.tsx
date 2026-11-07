import { adminHref } from "@leonaid/ui/base-paths";
import {
  useMutation,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import {
  Copy,
  Download,
  FileCheck,
  RefreshCw,
  RotateCw,
  TriangleAlert,
} from "lucide-react";
import { useState } from "react";

import type {
  LeonAidApiClient,
  OperationalCheckResponse,
  OperationalFailedJobResponse,
  OperationsOverviewResponse,
  PilotDailyReportResponse,
} from "@leonaid/api-client";
import {
  Badge,
  Button,
  ConfirmDialog,
  DetailProps,
  EmptyState,
  ErrorState,
  Icon,
  NextStep,
  SkeletonRows,
  StatusIcon,
  StatusLabel,
  StatusMessage,
  useOptionalToast,
} from "@leonaid/ui";

import {
  actionErrorMessage,
  type ActionErrorMessage,
} from "../action-admin/errors";
import { useActionErrorMessage } from "../action-admin/use-action-error";
import { formatDateTime } from "../shared/dates";
import { SupportDiagnosticsPanel } from "./support-diagnostics";

type Overview = UseQueryResult<OperationsOverviewResponse>;

const DEPENDENCY_LABELS: Readonly<Record<string, string>> = {
  mail: "E-Mail",
  rustfs: "Dateiablage",
  twenty: "CRM",
  worker: "Hintergrundjobs",
};

const CHECK_LABELS: Readonly<Record<OperationalCheckResponse["key"], string>> =
  {
    backup: "Datensicherung",
    disk: "Speicherplatz",
    tls: "HTTPS-Zertifikat",
  };

function checkValue(check: OperationalCheckResponse) {
  if (check.key === "backup") {
    const hours = check.value / 3_600;
    return hours < 1
      ? "Vor weniger als einer Stunde"
      : `Vor ${Math.round(hours).toLocaleString("de-DE")} Stunden`;
  }
  if (check.key === "disk") {
    return `${Math.round(check.value * 100).toLocaleString("de-DE")} % frei`;
  }
  const days = Math.max(0, Math.floor(check.value / 86_400));
  return `Noch ${days.toLocaleString("de-DE")} Tage gültig`;
}

const MONITORING_TEXT: Readonly<
  Record<OperationsOverviewResponse["monitoring"]["status"], [string, string]>
> = {
  ready: [
    "Geschützt",
    "Sicherung, Speicherplatz und HTTPS-Zertifikat sind in Ordnung.",
  ],
  attention: ["Prüfen", ""],
  unavailable: [
    "Nicht erreichbar",
    "Der Monitoringstatus ist gerade nicht erreichbar. Prüfen Sie den separaten Alarmkanal.",
  ],
  inactive: [
    "Nicht aktiv",
    "Das optionale Monitoring-Profil ist in dieser Umgebung nicht gestartet.",
  ],
};

const PILOT_STOP_REASON_LABELS: Readonly<Record<string, string>> = {
  active_p0_alert: "Aktiver P0-Alarm",
  active_p1_alert: "Aktiver P1-Alarm",
  active_p2_alert: "Aktiver P2-Hinweis",
  api_errors_observed: "API-Fehler seit Prozessstart beobachtet",
  backup_critical: "Datensicherung ist zu alt",
  backup_unavailable: "Datensicherung kann nicht geprüft werden",
  dependency_mail_unavailable: "E-Mail-Dienst nicht erreichbar",
  dependency_rustfs_unavailable: "Dateiablage nicht erreichbar",
  dependency_twenty_unavailable: "CRM nicht erreichbar",
  dependency_worker_unavailable: "Hintergrundjobs nicht erreichbar",
  disk_critical: "Freier Speicher unterschreitet den Grenzwert",
  disk_unavailable: "Speicherplatz kann nicht geprüft werden",
  monitoring_inactive: "Pilot-Monitoring ist nicht aktiv",
  monitoring_unavailable: "Pilot-Monitoring ist nicht erreichbar",
  outbox_dead_letter: "Fehlgeschlagene Hintergrundjobs vorhanden",
  tls_critical: "HTTPS-Zertifikat nähert sich dem Ablauf",
  tls_unavailable: "HTTPS-Zertifikat kann nicht geprüft werden",
};

function OverviewState({ overview }: { readonly overview: Overview }) {
  const error = useActionErrorMessage(overview.error);
  if (overview.isPending) return <SkeletonRows rows={5} />;
  return (
    <ErrorState
      onRetry={() => void overview.refetch()}
      title="Betriebsstatus nicht erreichbar"
    >
      {error?.message ?? "Der Server hat nicht geantwortet."}
    </ErrorState>
  );
}

/**
 * A failed 15-second refresh keeps the last overview on screen (with open
 * dialogs and generated results) and says so, instead of blanking the tab.
 */
function OverviewRefreshNotice({ overview }: { readonly overview: Overview }) {
  const error = useActionErrorMessage(overview.error);
  if (!overview.isError || overview.data === undefined) return null;
  return (
    <StatusMessage className="system-refresh-notice" tone="warning">
      <strong>Betriebsstatus konnte nicht aktualisiert werden</strong>
      <p>
        Angezeigt wird der Stand von {formatDateTime(overview.data.generatedAt)}
        . {error?.message ?? "Der Server hat nicht geantwortet."} LeonAid
        versucht es automatisch erneut.
      </p>
      <Button
        disabled={overview.isFetching}
        onClick={() => void overview.refetch()}
        size="sm"
        variant="secondary"
      >
        Jetzt neu laden
      </Button>
    </StatusMessage>
  );
}

function downloadPilotDailyReport(report: PilotDailyReportResponse) {
  const blob = new Blob([`${JSON.stringify(report, null, 2)}\n`], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `leonaid-pilot-daily-${report.generatedAt.slice(0, 10)}.json`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

const REPORT_STATUS: Readonly<
  Record<PilotDailyReportResponse["technicalStatus"], string>
> = {
  ready: "Technische Signale sind bereit",
  attention: "Befunde benötigen Aufmerksamkeit",
  blocked: "Pilot technisch nicht freigeben",
};

/** "Tagesreport": the technical daily check without personal data. */
function PilotDailyReportPanel({
  client,
}: {
  readonly client: LeonAidApiClient;
}) {
  const [error, setError] = useState<ActionErrorMessage>();
  const report = useMutation({
    mutationFn: () => client.getPilotDailyReport(),
    onMutate: () => setError(undefined),
    onError: (cause) => setError(actionErrorMessage(cause)),
  });
  const data = report.data;

  return (
    <section
      aria-labelledby="pilot-daily-report-title"
      className="panel"
      data-testid="pilot-daily-report"
    >
      <header className="panel-header">
        <h2 id="pilot-daily-report-title">Tagesreport</h2>
        <Button
          icon={RefreshCw}
          loading={report.isPending}
          onClick={() => report.mutate()}
          size="sm"
          variant="secondary"
        >
          Tagesreport erstellen
        </Button>
      </header>
      <div className="panel-pad stack">
        <p className="small muted">
          Prüft Dienste, Sicherung, Alarme, Hintergrundaufgaben, Speicher und
          HTTPS-Zertifikat. Der Report enthält keine fachlichen oder
          personenbezogenen Daten.
        </p>
        {error ? (
          <StatusMessage tone="error">
            <strong>Tagesreport konnte nicht erstellt werden</strong>
            <p>{error.message}</p>
          </StatusMessage>
        ) : null}
        {data ? (
          <div
            aria-live="polite"
            className="stack"
            data-testid="pilot-daily-report-result"
          >
            <p className="cluster">
              <StatusLabel
                shape={
                  data.technicalStatus === "ready"
                    ? "done"
                    : data.technicalStatus === "attention"
                      ? "review"
                      : "alert"
                }
                status={REPORT_STATUS[data.technicalStatus]}
              />
              <span className="small muted num">
                {data.dependencies.ready}/{data.dependencies.total} Dienste
              </span>
            </p>
            <DetailProps
              items={[
                { label: "Sicherung", value: data.monitoring.backupStatus },
                { label: "Alarmierung", value: data.monitoring.status },
                {
                  label: "Hintergrundaufgaben",
                  value: `${data.outbox.deadLetter} fehlgeschlagen`,
                },
                { label: "Speicher", value: data.monitoring.diskStatus },
                { label: "HTTPS", value: data.monitoring.tlsStatus },
                {
                  label: "Release",
                  value: <span className="mono">{data.release}</span>,
                },
              ]}
            />
            {data.stopReasons.length ? (
              <div>
                <h3 className="tab-h2">Stoppgründe und Hinweise</h3>
                <ul className="reason-list small">
                  {data.stopReasons.map((reason) => (
                    <li key={reason}>
                      <Icon icon={TriangleAlert} size={14} />
                      {PILOT_STOP_REASON_LABELS[reason] ?? reason}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            <NextStep
              action={
                <Button
                  icon={Download}
                  onClick={() => downloadPilotDailyReport(data)}
                  variant="primary"
                >
                  JSON herunterladen
                </Button>
              }
              consequence={data.nextStep}
            />
            <p className="small subtle">
              <span className="mono" title={data.checksumSha256}>
                SHA-256 {data.checksumSha256.slice(0, 16)}…
              </span>{" "}
              · {formatDateTime(data.generatedAt)}
            </p>
          </div>
        ) : null}
      </div>
    </section>
  );
}

/** Betrieb (prototype System.tsx Operations). */
export function OperationsTab({
  client,
  onShowJobs,
  overview,
}: {
  readonly client: LeonAidApiClient;
  readonly onShowJobs: () => void;
  readonly overview: Overview;
}) {
  // Only without any data: a failed refresh keeps the last overview.
  if (overview.data === undefined) return <OverviewState overview={overview} />;
  const data = overview.data;
  const down = data.dependencies.filter((item) => item.status !== "ready");
  const monitoring = data.monitoring;
  const [monitoringLabel, monitoringText] = MONITORING_TEXT[monitoring.status];

  return (
    <div className="system-grid" data-testid="operations-panel">
      <OverviewRefreshNotice overview={overview} />
      <section aria-labelledby="svc-title" className="panel">
        <header className="panel-header">
          <h2 id="svc-title">Dienste</h2>
          <span className="small muted">
            {down.length
              ? `${down.length} nicht erreichbar`
              : `${data.dependencies.length}/${data.dependencies.length} Dienste bereit`}{" "}
            · geprüft {formatDateTime(data.generatedAt)}
          </span>
        </header>
        <ul className="svc-list">
          {data.dependencies.map((dependency) => {
            const ready = dependency.status === "ready";
            return (
              <li
                className="svc-row"
                data-dependency={dependency.dependency}
                key={dependency.dependency}
              >
                <StatusIcon
                  label={ready ? "Bereit" : "Nicht erreichbar"}
                  size={16}
                  status={ready ? "done" : "alert"}
                />
                <span className="svc-name">
                  {DEPENDENCY_LABELS[dependency.dependency] ??
                    dependency.dependency}
                </span>
                <span className="svc-state">
                  {ready ? "Bereit" : "Nicht erreichbar"}
                </span>
                <span className="svc-detail small muted num">
                  {dependency.latencyMs.toLocaleString("de-DE")} ms
                </span>
              </li>
            );
          })}
        </ul>
        {down.length || data.failedJobs.length ? (
          <div className="callout tone-warn svc-callout">
            <Icon icon={TriangleAlert} size={16} />
            <div>
              <strong>
                {down.length
                  ? `${down
                      .map(
                        (item) =>
                          DEPENDENCY_LABELS[item.dependency] ?? item.dependency,
                      )
                      .join(", ")} nicht erreichbar.`
                  : `${data.failedJobs.length} Hintergrundaufgabe${data.failedJobs.length === 1 ? "" : "n"} fehlgeschlagen.`}
              </strong>{" "}
              LeonAid versucht wartende Aufgaben automatisch erneut;
              fehlgeschlagene starten Sie unter „Hintergrundaufgaben“.
              <div className="cluster svc-actions">
                <Button onClick={onShowJobs} size="sm" variant="secondary">
                  Betroffene Aufgaben ansehen
                </Button>
              </div>
            </div>
          </div>
        ) : null}
      </section>

      <section
        aria-labelledby="monitoring-title"
        className="panel"
        data-testid="monitoring-summary"
      >
        <header className="panel-header">
          <h2 id="monitoring-title">Pilot-Schutz</h2>
          <Badge
            tone={
              monitoring.status === "ready"
                ? "ok"
                : monitoring.status === "attention"
                  ? "warn"
                  : "neutral"
            }
          >
            {monitoringLabel}
          </Badge>
        </header>
        <p className="panel-pad small muted panel-intro">
          {monitoring.status === "attention"
            ? `${monitoring.activeAlerts.length} aktive ${
                monitoring.activeAlerts.length === 1
                  ? "Meldung benötigt"
                  : "Meldungen benötigen"
              } Aufmerksamkeit.`
            : monitoringText}
        </p>
        {monitoring.checks.length ? (
          <ul className="svc-list">
            {monitoring.checks.map((check) => {
              const ready = check.status === "ready";
              return (
                <li
                  className="svc-row"
                  data-testid={`monitoring-check-${check.key}`}
                  key={check.key}
                >
                  <StatusIcon
                    label={ready ? "In Ordnung" : "Handlung nötig"}
                    size={16}
                    status={ready ? "done" : "alert"}
                  />
                  <span className="svc-name">{CHECK_LABELS[check.key]}</span>
                  <span className="svc-state">
                    {ready ? "In Ordnung" : "Handlung nötig"}
                  </span>
                  <span className="svc-detail small muted">
                    {checkValue(check)}
                  </span>
                </li>
              );
            })}
          </ul>
        ) : null}
        {monitoring.activeAlerts.length ? (
          <ul
            aria-label="Aktive Alarme"
            className="svc-list"
            data-testid="active-alerts"
          >
            {monitoring.activeAlerts.map((alert) => (
              <li className="svc-row" key={alert.name}>
                <StatusIcon label={alert.severity} size={16} status="alert" />
                <span className="svc-name">{alert.summary}</span>
                <span className="svc-state">{alert.severity}</span>
                <span className="svc-detail small muted">
                  {alert.category} ·{" "}
                  <a href={alert.runbookUrl} rel="noreferrer" target="_blank">
                    Runbook öffnen
                  </a>
                </span>
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      {data.siteHosts?.length ? (
        <section
          aria-labelledby="site-hosts-ops-title"
          className="panel"
          data-testid="operations-site-hosts"
        >
          <header className="panel-header">
            <h2 id="site-hosts-ops-title">Domains für Aktionen</h2>
            <a className="small" href={adminHref("system/domains")}>
              Zu den Domains
            </a>
          </header>
          <ul className="svc-list">
            {data.siteHosts.map((host) => {
              const waiting = host.status === "verified" && !host.failedChecks;
              return (
                <li className="svc-row" key={host.hostname}>
                  <StatusIcon
                    label={waiting ? "Wartet" : "Handlung nötig"}
                    size={16}
                    status={waiting ? "progress" : "alert"}
                  />
                  <span className="svc-name">{host.hostname}</span>
                  <span className="svc-state">
                    {host.status === "disabled"
                      ? "Abgeschaltet"
                      : waiting
                        ? "Zertifikat ausstehend"
                        : `${host.failedChecks} Prüfung(en) fehlgeschlagen`}
                  </span>
                  <span className="svc-detail small muted">
                    {host.lastCheckResult ?? "Noch nicht geprüft."}
                    {host.status === "disabled" && host.liveBindings
                      ? ` ${host.liveBindings} Ausgabe(n) werden nicht ausgeliefert.`
                      : ""}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="ver-title" className="panel">
        <header className="panel-header">
          <h2 id="ver-title">Installation</h2>
          <Button
            icon={RefreshCw}
            onClick={() => void overview.refetch()}
            size="sm"
            variant="ghost"
          >
            Aktualisieren
          </Button>
        </header>
        <div className="panel-pad">
          <DetailProps
            items={[
              {
                label: "Letzte Prüfung",
                value: (
                  <span className="num">
                    {formatDateTime(data.generatedAt)}
                  </span>
                ),
              },
              {
                label: "Korrelations-ID",
                value: (
                  <code className="mono" title="Korrelations-ID dieser Prüfung">
                    {data.requestId}
                  </code>
                ),
              },
              {
                label: "API Ø-Latenz",
                value: (
                  <span className="num">
                    {data.api.averageLatencyMs.toLocaleString("de-DE")} ms ·{" "}
                    {data.api.requests} Anfragen · {data.api.errors}{" "}
                    Serverfehler
                  </span>
                ),
              },
              {
                label: "E-Mail-Aufgaben",
                value: (
                  <span className="num">
                    {data.mail.completed} erledigt · {data.mail.deadLetter}{" "}
                    fehlgeschlagen
                  </span>
                ),
              },
              {
                label: "Anmeldungen 24 h",
                value: (
                  <span className="num">
                    {data.login.completionsLast24h} erfolgreich ·{" "}
                    {data.login.challengesLast24h} Codes angefordert
                  </span>
                ),
              },
            ]}
          />
        </div>
      </section>

      <PilotDailyReportPanel client={client} />
      <SupportDiagnosticsPanel client={client} />
    </div>
  );
}

function CopyId({ value }: { readonly value: string }) {
  const toast = useOptionalToast();
  return (
    <button
      aria-label={`Job-ID ${value} kopieren`}
      className="copy-id"
      onClick={() => {
        void navigator.clipboard?.writeText(value).then(
          () => toast?.show({ title: "Job-ID kopiert.", tone: "success" }),
          () =>
            toast?.show({
              title: "Kopieren nicht möglich. Bitte manuell markieren.",
              tone: "error",
            }),
        );
      }}
      type="button"
    >
      <span className="mono">{value.slice(0, 8)}</span>
      <Icon icon={Copy} size={12} />
    </button>
  );
}

/** "12 s", "4 min", "3 h": how long the oldest due job has waited. */
export function waitedFor(seconds: number): string {
  const value = Math.max(0, Math.floor(seconds));
  if (value < 120) return `${value.toLocaleString("de-DE")} s`;
  if (value < 7_200)
    return `${Math.floor(value / 60).toLocaleString("de-DE")} min`;
  return `${Math.floor(value / 3_600).toLocaleString("de-DE")} h`;
}

/** Hintergrundaufgaben (prototype System.tsx Jobs): queue and dead letters. */
export function JobsTab({
  client,
  overview,
}: {
  readonly client: LeonAidApiClient;
  readonly overview: Overview;
}) {
  const queryClient = useQueryClient();
  const toast = useOptionalToast();
  const [asking, setAsking] = useState<OperationalFailedJobResponse>();
  const [error, setError] = useState<ActionErrorMessage>();
  const retry = useMutation({
    mutationFn: (job: OperationalFailedJobResponse) =>
      client.retryOperationalJob(job.id),
    onSuccess: async () => {
      setAsking(undefined);
      setError(undefined);
      toast?.show({ title: "Aufgabe neu eingeplant.", tone: "success" });
      await queryClient.invalidateQueries({
        queryKey: ["operations-overview"],
      });
    },
    onError: (cause) => {
      setAsking(undefined);
      setError(actionErrorMessage(cause));
    },
  });

  if (overview.data === undefined) return <OverviewState overview={overview} />;
  const data = overview.data;
  const jobs = data.failedJobs;

  return (
    <section aria-labelledby="jobs-title" className="stack">
      <h2 className="sr-only" id="jobs-title">
        Hintergrundaufgaben
      </h2>
      <OverviewRefreshNotice overview={overview} />
      <p className="small muted system-intro">
        Aufgaben, die LeonAid im Hintergrund erledigt: Rechnungen versenden,
        PDFs erzeugen, CRM abgleichen. Fehlgeschlagene Aufgaben starten Sie hier
        erneut. Fehlertexte enthalten keine personenbezogenen Daten.
      </p>
      <section
        aria-labelledby="queue-title"
        className="panel"
        data-testid="operations-outbox"
      >
        <header className="panel-header">
          <h3 id="queue-title">Warteschlange</h3>
          <span className="small muted num">
            geprüft {formatDateTime(data.generatedAt)}
          </span>
        </header>
        <div className="panel-pad">
          <DetailProps
            items={[
              {
                label: "Erledigt",
                value: <span className="num">{data.outbox.completed}</span>,
              },
              {
                label: "Wartend",
                value: <span className="num">{data.outbox.pending}</span>,
              },
              {
                label: "In Arbeit",
                value: <span className="num">{data.outbox.processing}</span>,
              },
              {
                label: "Fehlgeschlagen",
                value: <span className="num">{data.outbox.deadLetter}</span>,
              },
              {
                label: "Nächster Versuch",
                value: data.nextPendingAttemptAt
                  ? formatDateTime(data.nextPendingAttemptAt)
                  : "Keine wartenden Aufgaben",
              },
              {
                label: "Ältester fälliger",
                value:
                  data.oldestDuePendingAgeSeconds != null
                    ? `wartet seit ${waitedFor(data.oldestDuePendingAgeSeconds)}`
                    : "Keine fällige Aufgabe wartet",
              },
            ]}
          />
        </div>
      </section>
      {error ? (
        <StatusMessage tone="error">
          <p>{error.message}</p>
        </StatusMessage>
      ) : null}
      {jobs.length === 0 ? (
        <div data-testid="operations-no-jobs">
          <EmptyState
            description="Es gibt keine Aufgaben, die wiederholt werden müssen."
            icon={FileCheck}
            title="Keine fehlgeschlagenen Aufgaben"
          />
        </div>
      ) : (
        <div
          aria-label="Fehlgeschlagene Aufgaben"
          className="table-wrap"
          role="region"
          tabIndex={0}
        >
          <table className="table" data-testid="operations-jobs">
            <caption className="sr-only">Fehlgeschlagene Aufgaben</caption>
            <thead>
              <tr>
                <th scope="col">Status</th>
                <th scope="col">Aufgabe</th>
                <th scope="col">Versuche</th>
                <th scope="col">Fehler</th>
                <th scope="col">Job-ID</th>
                <th scope="col">
                  <span className="sr-only">Befehle</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr data-job-id={job.id} key={job.id}>
                  <td>
                    <StatusLabel shape="alert" status="Fehlgeschlagen" />
                  </td>
                  <td>
                    <div className="job-kind">{job.eventType}</div>
                    <div className="small muted">
                      {job.aggregateType} · {formatDateTime(job.failedAt)}
                    </div>
                  </td>
                  <td className="num">
                    {job.attempts}
                    {job.manualRetryCount ? (
                      <div className="small muted">
                        {job.manualRetryCount}× manuell
                      </div>
                    ) : null}
                  </td>
                  <td className="job-error mono small">{job.lastErrorCode}</td>
                  <td>
                    <CopyId value={job.id} />
                  </td>
                  <td className="right">
                    <Button
                      data-testid={`retry-job-${job.id}`}
                      disabled={retry.isPending}
                      icon={RotateCw}
                      onClick={() => setAsking(job)}
                      size="sm"
                      variant="secondary"
                    >
                      Erneut versuchen
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ConfirmDialog
        confirmLabel="Erneut versuchen"
        description={
          asking
            ? `„${asking.eventType}“ wird sofort erneut ausgeführt. LeonAid wiederholt nur sicher wiederholbare Aufgaben; der Versuch wird protokolliert.`
            : ""
        }
        onConfirm={() => {
          if (asking) retry.mutate(asking);
        }}
        onOpenChange={(open) => {
          if (!open && !retry.isPending) setAsking(undefined);
        }}
        open={Boolean(asking)}
        pending={retry.isPending}
        title="Aufgabe erneut versuchen?"
      />
    </section>
  );
}
