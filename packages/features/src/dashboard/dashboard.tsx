import {
  Activity01Icon,
  ArrowRight02Icon,
  ClockAlertIcon,
  Invoice03Icon,
  Package01Icon,
  Target01Icon,
  UserMultiple02Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import type {
  CurrentIdentityResponse,
  DashboardMetricDefinitionResponse,
  DashboardPipelineResponse,
  DashboardResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, EmptyState, StatusMessage } from "@leonaid/ui";

import { actionErrorMessage } from "../action-admin/errors";

type DashboardMode = "acquirer" | "charity_admin";

interface RoleDashboardPageProps {
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
  readonly mode: DashboardMode;
}

const pipelineStages = [
  ["open", "Offen"],
  ["contacted", "Kontaktiert"],
  ["committed", "Zugesagt"],
  ["declined", "Abgesagt"],
  ["handedOver", "Übergeben"],
] as const;

function formatMoney(amountMinor: number, currency: string) {
  return new Intl.NumberFormat("de-DE", {
    currency,
    style: "currency",
  }).format(amountMinor / 100);
}

function formatGoalValue(value: string, unit: string | null, currency: string) {
  const number = Number(value);
  if (unit === currency && /^[A-Z]{3}$/.test(currency)) {
    return new Intl.NumberFormat("de-DE", {
      currency,
      maximumFractionDigits: 2,
      style: "currency",
    }).format(number);
  }
  return `${new Intl.NumberFormat("de-DE", {
    maximumFractionDigits: 2,
  }).format(number)}${unit ? ` ${unit}` : ""}`;
}

function selectedActionFromUrl(
  memberships: ReadonlyArray<{ readonly actionId: string }>,
) {
  const requested = new URLSearchParams(window.location.search).get("action");
  return (
    memberships.find((membership) => membership.actionId === requested)
      ?.actionId ??
    memberships[0]?.actionId ??
    ""
  );
}

function setActionInUrl(actionId: string) {
  const url = new URL(window.location.href);
  url.searchParams.set("action", actionId);
  window.history.replaceState({}, "", `${url.pathname}${url.search}`);
}

function definition(
  dashboard: DashboardResponse,
  key: string,
): DashboardMetricDefinitionResponse | undefined {
  return dashboard.metricDefinitions.find((item) => item.key === key);
}

function GoalProgress({
  dashboard,
}: {
  readonly dashboard: DashboardResponse;
}) {
  const { goal } = dashboard;
  const actual = formatGoalValue(goal.actualValue, goal.unit, goal.currency);
  const target =
    goal.targetValue === null
      ? null
      : formatGoalValue(goal.targetValue, goal.unit, goal.currency);
  const percentage =
    goal.progressBasisPoints === null || goal.progressBasisPoints === undefined
      ? null
      : goal.progressBasisPoints / 100;
  const spokenStatus =
    target === null || percentage === null
      ? `Aktionsstand: ${actual}. Ein Zielwert ist noch nicht vollständig gepflegt.`
      : `Aktionsziel: ${actual} von ${target} erreicht, ${new Intl.NumberFormat(
          "de-DE",
          { maximumFractionDigits: 2 },
        ).format(percentage)} Prozent.`;

  return (
    <section
      aria-labelledby="dashboard-goal-heading"
      className="dashboard-goal"
      data-configured={goal.configured}
      data-testid="dashboard-goal"
    >
      <div className="dashboard-goal__intro">
        <span aria-hidden="true" className="dashboard-goal__icon">
          <HugeiconsIcon icon={Target01Icon} size={22} strokeWidth={1.7} />
        </span>
        <div>
          <p>Gemeinsames Aktionsziel</p>
          <h2 id="dashboard-goal-heading">
            {goal.configured ? "Wir sind auf Kurs." : "Der Stand ist sichtbar."}
          </h2>
        </div>
      </div>
      <div className="dashboard-goal__value">
        {percentage === null ? (
          <strong>{actual}</strong>
        ) : (
          <>
            <strong>
              {new Intl.NumberFormat("de-DE").format(percentage)} %
            </strong>
            <span>
              {actual} von {target}
            </span>
          </>
        )}
      </div>
      {percentage === null ? (
        <p className="dashboard-goal__configuration">
          Sobald Zielwert und Einheit gepflegt sind, zeigt LeonAid hier den
          Fortschritt.
        </p>
      ) : (
        <progress
          aria-label="Fortschritt des Aktionsziels"
          aria-valuetext={spokenStatus}
          max={100}
          value={Math.min(percentage, 100)}
        >
          {percentage} %
        </progress>
      )}
      <p className="dashboard-goal__spoken" data-testid="goal-status">
        {spokenStatus}
      </p>
    </section>
  );
}

function Pipeline({
  baseHref,
  counts,
  title,
}: {
  readonly baseHref: string;
  readonly counts: DashboardPipelineResponse;
  readonly title: string;
}) {
  return (
    <section
      aria-labelledby="dashboard-pipeline-heading"
      className="dashboard-pipeline"
      data-testid="dashboard-pipeline"
    >
      <header>
        <div>
          <p>Sponsor-Status</p>
          <h2 id="dashboard-pipeline-heading">{title}</h2>
        </div>
        <span>{counts.total} Zuordnungen</span>
      </header>
      {counts.total === 0 ? (
        <EmptyState
          action={
            <a className="ui-button ui-button--secondary" href={baseHref}>
              Akquise öffnen
            </a>
          }
          description="Lege den ersten Sponsor an oder ordne einen bestehenden Kontakt zu."
          title="Die Pipeline ist noch leer"
        />
      ) : (
        <ol>
          {pipelineStages.map(([key, label]) => {
            const count = counts[key];
            const href = `${baseHref}${baseHref.includes("?") ? "&" : "?"}status=${
              key === "handedOver" ? "handed_over" : key
            }`;
            return (
              <li key={key}>
                <a href={href}>
                  <span>{label}</span>
                  <strong>{count}</strong>
                  <HugeiconsIcon
                    aria-hidden="true"
                    icon={ArrowRight02Icon}
                    size={17}
                    strokeWidth={1.8}
                  />
                </a>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

function MetricDefinitions({
  items,
}: {
  readonly items: ReadonlyArray<DashboardMetricDefinitionResponse>;
}) {
  return (
    <details className="dashboard-definitions">
      <summary>So werden die Kennzahlen berechnet</summary>
      <dl>
        {items.map((item) => (
          <div key={item.key}>
            <dt>
              <a href={item.href}>{item.label}</a>
            </dt>
            <dd>{item.description}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

function AcquirerDashboard({
  dashboard,
}: {
  readonly dashboard: DashboardResponse;
}) {
  const data = dashboard.acquirer;
  if (data === null) {
    return (
      <StatusMessage tone="error">
        <strong>Persönliche Akquise-Sicht nicht verfügbar</strong>
        <p>Für diese Aktion fehlt deine aktive Akquisiteur-Zuordnung.</p>
      </StatusMessage>
    );
  }
  const pipelineHref =
    definition(dashboard, "acquirer.pipeline")?.href ?? "/app/sponsors";
  const reminderHref =
    definition(dashboard, "acquirer.reminders")?.href ??
    "/app/activities?view=contacts";
  const nextHref =
    data.reminders.overdue > 0
      ? `${reminderHref}&urgency=overdue`
      : data.reminders.today > 0
        ? `${reminderHref}&urgency=today`
        : `${pipelineHref}&status=open`;
  const nextLabel =
    data.reminders.overdue > 0
      ? `${data.reminders.overdue} überfällige ${
          data.reminders.overdue === 1 ? "Wiedervorlage" : "Wiedervorlagen"
        } klären`
      : data.reminders.today > 0
        ? `${data.reminders.today} heutige ${
            data.reminders.today === 1 ? "Wiedervorlage" : "Wiedervorlagen"
          } öffnen`
        : "Mit offenen Sponsoren weiterarbeiten";

  return (
    <>
      <section className="dashboard-next" data-testid="dashboard-next-step">
        <span aria-hidden="true">
          <HugeiconsIcon icon={ClockAlertIcon} size={24} strokeWidth={1.7} />
        </span>
        <div>
          <p>Dein nächster sinnvoller Schritt</p>
          <h2>{nextLabel}</h2>
          <span>
            {data.reminders.upcoming} weitere geplant ·{" "}
            {data.reminders.unscheduled} ohne Termin
          </span>
        </div>
        <a className="ui-button ui-button--primary" href={nextHref}>
          Jetzt öffnen
          <HugeiconsIcon
            aria-hidden="true"
            icon={ArrowRight02Icon}
            size={18}
            strokeWidth={1.8}
          />
        </a>
      </section>

      <div className="dashboard-personal-metrics">
        <a href={`${reminderHref}&urgency=overdue`}>
          <HugeiconsIcon
            aria-hidden="true"
            icon={ClockAlertIcon}
            size={20}
            strokeWidth={1.8}
          />
          <span>Überfällig</span>
          <strong>{data.reminders.overdue}</strong>
        </a>
        <a href={`${reminderHref}&urgency=today`}>
          <HugeiconsIcon
            aria-hidden="true"
            icon={ClockAlertIcon}
            size={20}
            strokeWidth={1.8}
          />
          <span>Heute</span>
          <strong>{data.reminders.today}</strong>
        </a>
        <a
          href={
            definition(dashboard, "acquirer.activities")?.href ??
            "/app/activities?view=contacts"
          }
        >
          <HugeiconsIcon
            aria-hidden="true"
            icon={Activity01Icon}
            size={20}
            strokeWidth={1.8}
          />
          <span>Dokumentiert</span>
          <strong>{data.activityCount}</strong>
        </a>
      </div>

      <Pipeline
        baseHref={pipelineHref}
        counts={data.pipeline}
        title="Deine persönliche Pipeline"
      />
    </>
  );
}

function AdminDashboard({
  dashboard,
}: {
  readonly dashboard: DashboardResponse;
}) {
  const data = dashboard.charityAdmin;
  if (data === null) {
    return (
      <StatusMessage tone="error">
        <strong>Admin-Sicht nicht verfügbar</strong>
        <p>Für diese Aktion fehlt deine aktive Charity-Admin-Zuordnung.</p>
      </StatusMessage>
    );
  }
  const pipelineHref =
    definition(dashboard, "admin.pipeline")?.href ?? "/admin/acquisition";
  const commitmentsHref =
    definition(dashboard, "admin.commitments")?.href ?? "/admin/orders";
  const invoicedHref =
    definition(dashboard, "admin.invoiced")?.href ?? "/admin/invoices";
  const openHref =
    definition(dashboard, "admin.open_receivables")?.href ??
    "/admin/invoices?status=open";

  return (
    <>
      <section
        aria-label="Aktionskennzahlen"
        className="dashboard-admin-metrics"
        data-testid="admin-dashboard-metrics"
      >
        <a href={commitmentsHref}>
          <span aria-hidden="true">
            <HugeiconsIcon icon={Package01Icon} size={20} strokeWidth={1.8} />
          </span>
          <small>Bestellungen</small>
          <strong>{data.commitments.activeTotal}</strong>
          <p>
            {data.commitments.totalBoxes} Boxen · {data.commitments.totalPieces}{" "}
            Stück
          </p>
        </a>
        <a href={commitmentsHref}>
          <span aria-hidden="true">
            <HugeiconsIcon
              icon={UserMultiple02Icon}
              size={20}
              strokeWidth={1.8}
            />
          </span>
          <small>Bestellwert</small>
          <strong>
            {formatMoney(
              data.commitments.activeTotalMinor,
              data.commitments.currency,
            )}
          </strong>
          <p>ohne stornierte Bestellungen</p>
        </a>
        <a href={invoicedHref}>
          <span aria-hidden="true">
            <HugeiconsIcon icon={Invoice03Icon} size={20} strokeWidth={1.8} />
          </span>
          <small>Fakturiert</small>
          <strong>
            {formatMoney(
              data.invoices.invoicedAmountMinor,
              data.invoices.currency,
            )}
          </strong>
          <p>ausgestellt, versendet oder bezahlt</p>
        </a>
        <a href={openHref}>
          <span aria-hidden="true">
            <HugeiconsIcon icon={ClockAlertIcon} size={20} strokeWidth={1.8} />
          </span>
          <small>Offene Posten</small>
          <strong>
            {formatMoney(data.invoices.openAmountMinor, data.invoices.currency)}
          </strong>
          <p>
            {data.invoices.open}{" "}
            {data.invoices.open === 1 ? "Rechnung" : "Rechnungen"}
          </p>
        </a>
      </section>

      <Pipeline
        baseHref={pipelineHref}
        counts={data.pipeline}
        title="Pipeline der gesamten Aktion"
      />
    </>
  );
}

export function RoleDashboardPage({
  client,
  identity,
  mode,
}: RoleDashboardPageProps) {
  const memberships = useMemo(
    () => [
      ...new Map(
        identity.actionMemberships
          .filter((membership) => membership.role === mode)
          .map((membership) => [membership.actionId, membership]),
      ).values(),
    ],
    [identity.actionMemberships, mode],
  );
  const [actionId, setActionId] = useState(() =>
    selectedActionFromUrl(memberships),
  );
  const dashboard = useQuery({
    enabled: Boolean(actionId),
    queryFn: () => client.getActionDashboard(actionId),
    queryKey: ["dashboard", mode, actionId],
  });

  if (memberships.length === 0) {
    return (
      <EmptyState
        description={
          mode === "acquirer"
            ? "Sobald du einer Charity-Aktion als Akquisiteur zugeordnet bist, erscheint hier dein persönlicher Arbeitsstand."
            : "Sobald du eine Charity-Aktion verwaltest, erscheint hier der gemeinsame Arbeitsstand."
        }
        icon={<HugeiconsIcon icon={Target01Icon} size={25} strokeWidth={1.7} />}
        title="Noch keine passende Charity-Aktion"
      />
    );
  }

  return (
    <div className="dashboard-page" data-dashboard-mode={mode}>
      <header className="dashboard-header">
        <div>
          <p>
            {mode === "acquirer"
              ? "Dein Akquise-Tag"
              : "Charity-Aktion im Blick"}
          </p>
          <h1>
            {mode === "acquirer"
              ? `Guten Tag, ${identity.displayName.split(" ")[0]}.`
              : "Was jetzt zählt."}
          </h1>
          <span>
            {mode === "acquirer"
              ? "Wiedervorlagen zuerst, Fortschritt immer im Blick."
              : "Vom Sponsor-Kontakt bis zum offenen Rechnungsbetrag."}
          </span>
        </div>
        <label className="dashboard-action-picker">
          <span>Charity-Aktion</span>
          <select
            data-testid="dashboard-action"
            onChange={(event) => {
              setActionId(event.target.value);
              setActionInUrl(event.target.value);
            }}
            value={actionId}
          >
            {memberships.map((membership) => (
              <option key={membership.actionId} value={membership.actionId}>
                {membership.actionName}
              </option>
            ))}
          </select>
        </label>
      </header>

      {dashboard.isPending ? (
        <div
          aria-label="Dashboard wird geladen"
          className="dashboard-loading"
          role="status"
        >
          <span />
          <p>Aktionsstand wird berechnet …</p>
        </div>
      ) : dashboard.isError ? (
        <StatusMessage tone="error">
          <strong>Aktionsstand nicht erreichbar</strong>
          <p>{actionErrorMessage(dashboard.error).message}</p>
          <Button onClick={() => void dashboard.refetch()} variant="secondary">
            Erneut laden
          </Button>
        </StatusMessage>
      ) : (
        <>
          <GoalProgress dashboard={dashboard.data} />
          {mode === "acquirer" ? (
            <AcquirerDashboard dashboard={dashboard.data} />
          ) : (
            <AdminDashboard dashboard={dashboard.data} />
          )}
          <MetricDefinitions items={dashboard.data.metricDefinitions} />
        </>
      )}
    </div>
  );
}
