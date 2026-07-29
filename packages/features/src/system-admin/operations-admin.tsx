import {
  Alert02Icon,
  CheckmarkCircle02Icon,
  Clock01Icon,
  Download04Icon,
  File02Icon,
  RefreshIcon,
  ServerStack01Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type LeonAidApiClient,
  type OperationalAlertResponse,
  type OperationalCheckResponse,
  type OperationalDependencyResponse,
  type OperationalFailedJobResponse,
  type PilotDailyReportResponse,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

import { actionErrorMessage } from "../action-admin/errors";

const DEPENDENCY_LABELS: Record<string, string> = {
  mail: "E-Mail",
  rustfs: "Dateiablage",
  twenty: "CRM",
  worker: "Hintergrundjobs",
};

function formatDate(value: string) {
  return new Intl.DateTimeFormat("de-DE", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
}

function DependencyCard({
  dependency,
}: {
  readonly dependency: OperationalDependencyResponse;
}) {
  const ready = dependency.status === "ready";
  return (
    <article
      className={`operations-dependency ${ready ? "is-ready" : "is-down"}`}
      data-dependency={dependency.dependency}
    >
      <HugeiconsIcon
        aria-hidden="true"
        icon={ready ? CheckmarkCircle02Icon : Alert02Icon}
        size={22}
        strokeWidth={1.8}
      />
      <div>
        <span>{DEPENDENCY_LABELS[dependency.dependency]}</span>
        <strong>{ready ? "Bereit" : "Nicht erreichbar"}</strong>
      </div>
      <small>{dependency.latencyMs.toLocaleString("de-DE")} ms</small>
    </article>
  );
}

const CHECK_LABELS: Record<OperationalCheckResponse["key"], string> = {
  backup: "Datensicherung",
  disk: "Speicherplatz",
  tls: "HTTPS-Zertifikat",
};

function formatCheckValue(check: OperationalCheckResponse) {
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

function MonitoringCheckCard({
  check,
}: {
  readonly check: OperationalCheckResponse;
}) {
  const ready = check.status === "ready";
  return (
    <article
      className={`operations-monitoring-check ${
        ready ? "is-ready" : "is-critical"
      }`}
      data-testid={`monitoring-check-${check.key}`}
    >
      <div className="operations-monitoring-check__icon" aria-hidden="true">
        <HugeiconsIcon
          icon={ready ? CheckmarkCircle02Icon : Alert02Icon}
          size={20}
          strokeWidth={1.8}
        />
      </div>
      <div>
        <span>{CHECK_LABELS[check.key]}</span>
        <strong>{ready ? "In Ordnung" : "Handlung nötig"}</strong>
        <small>{formatCheckValue(check)}</small>
      </div>
    </article>
  );
}

function ActiveAlert({ alert }: { readonly alert: OperationalAlertResponse }) {
  return (
    <article className="operations-active-alert">
      <span>{alert.severity}</span>
      <div>
        <strong>{alert.summary}</strong>
        <small>{alert.category}</small>
      </div>
      <a href={alert.runbookUrl} rel="noreferrer" target="_blank">
        Runbook öffnen
      </a>
    </article>
  );
}

function FailedJobCard({
  job,
  pending,
  onRetry,
}: {
  readonly job: OperationalFailedJobResponse;
  readonly pending: boolean;
  readonly onRetry: (job: OperationalFailedJobResponse) => void;
}) {
  return (
    <article className="operations-job" data-job-id={job.id}>
      <div className="operations-job__status" aria-hidden="true">
        <HugeiconsIcon icon={Alert02Icon} size={20} strokeWidth={1.8} />
      </div>
      <div className="operations-job__copy">
        <p>{job.eventType}</p>
        <h3>{job.lastErrorCode}</h3>
        <small>
          {job.aggregateType} · Versuch {job.attempts} ·{" "}
          {formatDate(job.failedAt)}
        </small>
      </div>
      <Button
        data-testid={`retry-job-${job.id}`}
        disabled={pending}
        onClick={() => onRetry(job)}
        variant="secondary"
      >
        <HugeiconsIcon
          aria-hidden="true"
          icon={RefreshIcon}
          size={17}
          strokeWidth={1.8}
        />
        {pending ? "Wird gestartet …" : "Sicher wiederholen"}
      </Button>
    </article>
  );
}

const PILOT_STOP_REASON_LABELS: Record<string, string> = {
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

function PilotDailyReportCard({
  client,
}: {
  readonly client: LeonAidApiClient;
}) {
  const report = useMutation({
    mutationFn: () => client.getPilotDailyReport(),
  });
  const error = report.error ? actionErrorMessage(report.error) : null;

  return (
    <section
      aria-labelledby="pilot-daily-report-title"
      className="pilot-daily-report"
      data-testid="pilot-daily-report"
    >
      <header className="pilot-daily-report__header">
        <div className="pilot-daily-report__heading-icon" aria-hidden="true">
          <HugeiconsIcon icon={File02Icon} size={21} strokeWidth={1.8} />
        </div>
        <div>
          <p className="feature-admin-header__eyebrow">
            Pilotbetrieb · täglicher Nachweis
          </p>
          <h3 id="pilot-daily-report-title">
            Technischen Tagesreport erstellen
          </h3>
          <p>
            Prüft Abhängigkeiten, Backup, Alarme, Outbox, Speicher und
            HTTPS-Zertifikat. Der Report enthält keine fachlichen oder
            personenbezogenen Daten.
          </p>
        </div>
        <Button
          disabled={report.isPending}
          onClick={() => report.mutate()}
          variant="secondary"
        >
          <HugeiconsIcon
            aria-hidden="true"
            icon={RefreshIcon}
            size={17}
            strokeWidth={1.8}
          />
          {report.isPending ? "Wird geprüft …" : "Tagesreport erstellen"}
        </Button>
      </header>

      {error && (
        <StatusMessage tone="error">
          <h3>Tagesreport konnte nicht erstellt werden</h3>
          <p>{error.message}</p>
        </StatusMessage>
      )}

      {report.data && (
        <article
          aria-live="polite"
          className={`pilot-daily-report__result is-${report.data.technicalStatus}`}
          data-testid="pilot-daily-report-result"
        >
          <div className="pilot-daily-report__result-header">
            <div>
              <span>Technische Tagesprüfung</span>
              <h4>
                {report.data.technicalStatus === "ready"
                  ? "Technische Signale sind bereit"
                  : report.data.technicalStatus === "attention"
                    ? "Befunde benötigen Aufmerksamkeit"
                    : "Pilot technisch nicht freigeben"}
              </h4>
            </div>
            <strong>
              {report.data.dependencies.ready}/{report.data.dependencies.total}{" "}
              Dienste
            </strong>
          </div>

          <dl className="pilot-daily-report__coverage">
            <div>
              <dt>Backup</dt>
              <dd>{report.data.monitoring.backupStatus}</dd>
            </div>
            <div>
              <dt>Alarmierung</dt>
              <dd>{report.data.monitoring.status}</dd>
            </div>
            <div>
              <dt>Outbox</dt>
              <dd>{report.data.outbox.deadLetter} fehlgeschlagen</dd>
            </div>
            <div>
              <dt>Speicher</dt>
              <dd>{report.data.monitoring.diskStatus}</dd>
            </div>
            <div>
              <dt>HTTPS</dt>
              <dd>{report.data.monitoring.tlsStatus}</dd>
            </div>
            <div>
              <dt>Release</dt>
              <dd>{report.data.release}</dd>
            </div>
          </dl>

          {report.data.stopReasons.length > 0 && (
            <div className="pilot-daily-report__reasons">
              <strong>Stopgründe und Hinweise</strong>
              <ul>
                {report.data.stopReasons.map((reason) => (
                  <li key={reason}>
                    {PILOT_STOP_REASON_LABELS[reason] ?? reason}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="pilot-daily-report__next">
            <div>
              <strong>Nächster Schritt</strong>
              <p>{report.data.nextStep}</p>
              <small title={report.data.checksumSha256}>
                SHA-256 {report.data.checksumSha256.slice(0, 16)}… ·{" "}
                {formatDate(report.data.generatedAt)}
              </small>
            </div>
            <Button
              onClick={() => downloadPilotDailyReport(report.data)}
              variant="secondary"
            >
              <HugeiconsIcon
                aria-hidden="true"
                icon={Download04Icon}
                size={17}
                strokeWidth={1.8}
              />
              JSON herunterladen
            </Button>
          </div>
        </article>
      )}
    </section>
  );
}

export function OperationsAdminPanel({
  client,
}: {
  readonly client: LeonAidApiClient;
}) {
  const queryClient = useQueryClient();
  const overview = useQuery({
    queryFn: () => client.getOperationsOverview(),
    queryKey: ["operations-overview"],
    refetchInterval: 15_000,
    retry: false,
  });
  const retry = useMutation({
    mutationFn: (job: OperationalFailedJobResponse) =>
      client.retryOperationalJob(job.id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["operations-overview"],
      });
    },
  });

  if (overview.isPending) {
    return (
      <section
        aria-label="Betriebsstatus wird geladen"
        className="operations-panel"
      >
        <div aria-live="polite" className="action-loading" role="status">
          <span aria-hidden="true" />
          <h2>Betriebsstatus wird geprüft</h2>
          <p>LeonAid fragt CRM, Dateiablage und E-Mail direkt ab.</p>
        </div>
      </section>
    );
  }

  if (overview.isError) {
    return (
      <section className="operations-panel">
        <StatusMessage tone="error">
          <h2>Betriebsstatus nicht erreichbar</h2>
          <p>{actionErrorMessage(overview.error).message}</p>
          <Button onClick={() => void overview.refetch()} variant="secondary">
            Erneut prüfen
          </Button>
        </StatusMessage>
      </section>
    );
  }

  const readyCount = overview.data.dependencies.filter(
    (item) => item.status === "ready",
  ).length;
  const failedJobs = overview.data.failedJobs;
  const monitoring = overview.data.monitoring;
  const retryError = retry.error ? actionErrorMessage(retry.error) : null;

  return (
    <section
      aria-labelledby="operations-title"
      className="operations-panel"
      data-testid="operations-panel"
      id="betrieb"
    >
      <header className="operations-panel__header">
        <div>
          <p className="feature-admin-header__eyebrow">
            Live · direkt aus den Systemen
          </p>
          <h2 id="operations-title">Betrieb & fehlgeschlagene Jobs</h2>
          <p>
            Erkenne Störungen getrennt nach Dienst und starte ausschließlich
            sicher wiederholbare Dead-Letter-Jobs erneut.
          </p>
        </div>
        <Button onClick={() => void overview.refetch()} variant="secondary">
          <HugeiconsIcon
            aria-hidden="true"
            icon={RefreshIcon}
            size={17}
            strokeWidth={1.8}
          />
          Aktualisieren
        </Button>
      </header>

      <div className="operations-summary">
        <div className="operations-summary__state">
          <HugeiconsIcon
            aria-hidden="true"
            icon={
              readyCount === overview.data.dependencies.length
                ? CheckmarkCircle02Icon
                : Alert02Icon
            }
            size={24}
            strokeWidth={1.8}
          />
          <div>
            <strong>
              {readyCount}/{overview.data.dependencies.length} Dienste bereit
            </strong>
            <span>Letzte Prüfung {formatDate(overview.data.generatedAt)}</span>
          </div>
        </div>
        <code title="Korrelations-ID dieser Prüfung">
          {overview.data.requestId}
        </code>
      </div>

      <div className="operations-dependencies">
        {overview.data.dependencies.map((dependency) => (
          <DependencyCard dependency={dependency} key={dependency.dependency} />
        ))}
      </div>

      <section
        aria-labelledby="monitoring-title"
        className={`operations-monitoring is-${monitoring.status}`}
        data-testid="monitoring-summary"
      >
        <div className="operations-monitoring__heading">
          <div>
            <p className="feature-admin-header__eyebrow">
              Alarmierung · unabhängiger Kanal
            </p>
            <h3 id="monitoring-title">Pilot-Schutz</h3>
            <p>
              {monitoring.status === "ready"
                ? "Backup, Speicherplatz und HTTPS-Zertifikat sind in Ordnung."
                : monitoring.status === "attention"
                  ? `${monitoring.activeAlerts.length} aktive ${
                      monitoring.activeAlerts.length === 1
                        ? "Meldung"
                        : "Meldungen"
                    } benötigen Aufmerksamkeit.`
                  : monitoring.status === "unavailable"
                    ? "Der Monitoringstatus ist gerade nicht erreichbar. Prüfe den separaten Alarmkanal."
                    : "Das optionale Monitoring-Profil ist in dieser Umgebung nicht gestartet."}
            </p>
          </div>
          <span>
            {monitoring.status === "ready"
              ? "Geschützt"
              : monitoring.status === "attention"
                ? "Prüfen"
                : monitoring.status === "unavailable"
                  ? "Nicht erreichbar"
                  : "Nicht aktiv"}
          </span>
        </div>

        {monitoring.checks.length > 0 && (
          <div className="operations-monitoring-checks">
            {monitoring.checks.map((check) => (
              <MonitoringCheckCard check={check} key={check.key} />
            ))}
          </div>
        )}

        {monitoring.activeAlerts.length > 0 && (
          <div
            aria-label="Aktive Alarme"
            className="operations-active-alerts"
            data-testid="active-alerts"
          >
            {monitoring.activeAlerts.map((alert) => (
              <ActiveAlert alert={alert} key={alert.name} />
            ))}
          </div>
        )}
      </section>

      <div aria-label="Betriebskennzahlen" className="operations-metrics">
        <article>
          <HugeiconsIcon
            aria-hidden="true"
            icon={Clock01Icon}
            size={19}
            strokeWidth={1.8}
          />
          <span>API Ø-Latenz</span>
          <strong>
            {overview.data.api.averageLatencyMs.toLocaleString("de-DE")} ms
          </strong>
          <small>
            {overview.data.api.requests} Requests · {overview.data.api.errors}{" "}
            Serverfehler
          </small>
        </article>
        <article>
          <HugeiconsIcon
            aria-hidden="true"
            icon={ServerStack01Icon}
            size={19}
            strokeWidth={1.8}
          />
          <span>Outbox</span>
          <strong>{overview.data.outbox.pending} wartend</strong>
          <small>{overview.data.outbox.deadLetter} fehlgeschlagen</small>
        </article>
        <article>
          <HugeiconsIcon
            aria-hidden="true"
            icon={ServerStack01Icon}
            size={19}
            strokeWidth={1.8}
          />
          <span>E-Mail-Jobs</span>
          <strong>{overview.data.mail.completed} erledigt</strong>
          <small>{overview.data.mail.deadLetter} fehlgeschlagen</small>
        </article>
        <article>
          <HugeiconsIcon
            aria-hidden="true"
            icon={CheckmarkCircle02Icon}
            size={19}
            strokeWidth={1.8}
          />
          <span>Login · 24 Stunden</span>
          <strong>{overview.data.login.completionsLast24h} erfolgreich</strong>
          <small>
            {overview.data.login.challengesLast24h} Codes angefordert
          </small>
        </article>
      </div>

      <PilotDailyReportCard client={client} />

      <div className="operations-jobs">
        <div className="operations-jobs__heading">
          <div>
            <p className="feature-admin-header__eyebrow">Arbeitsvorrat</p>
            <h3>Fehlgeschlagene Jobs</h3>
          </div>
          <span>{failedJobs.length}</span>
        </div>
        {retryError && (
          <StatusMessage tone="error">
            <p>{retryError.message}</p>
          </StatusMessage>
        )}
        {failedJobs.length === 0 ? (
          <div className="operations-empty" data-testid="operations-no-jobs">
            <HugeiconsIcon
              aria-hidden="true"
              icon={CheckmarkCircle02Icon}
              size={22}
              strokeWidth={1.8}
            />
            <div>
              <strong>Keine fehlgeschlagenen Jobs</strong>
              <p>Der Dead-Letter-Arbeitsvorrat ist leer.</p>
            </div>
          </div>
        ) : (
          <div className="operations-job-list">
            {failedJobs.map((job) => (
              <FailedJobCard
                job={job}
                key={job.id}
                onRetry={(selected) => retry.mutate(selected)}
                pending={retry.isPending && retry.variables?.id === job.id}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
