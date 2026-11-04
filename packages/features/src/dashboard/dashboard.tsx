import { useActionInUrl } from "../action-admin/action-location";

import {
  Activity,
  ArrowRight,
  Clock,
  Inbox,
  type LucideIcon,
  MailWarning,
  ReceiptEuro,
  ShoppingBasket,
  Target,
  Truck,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import {
  type ReactNode,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import type {
  CurrentIdentityResponse,
  DashboardMetricDefinitionResponse,
  DashboardPipelineResponse,
  DashboardResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Button,
  buttonClassName,
  EmptyState,
  Icon,
  Meter,
  NextStep,
  StatusIcon,
  type StatusShape,
  StatusMessage,
} from "@leonaid/ui";

import { actionErrorMessage } from "../action-admin/errors";
import { snapshotWindowLabel } from "../commitments/order-format";
import { formatQuantities } from "../commitments/quantities";

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
  const { goal, beneficiaries = [] } = dashboard;
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
          <Icon icon={Target} size={20} />
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
      <p className="sr-only" data-testid="goal-status">
        {spokenStatus}
      </p>
      <div className="dashboard-goal__beneficiaries">
        <span>Zugunsten von</span>
        {beneficiaries.length === 0 ? (
          <p>Noch keine Begünstigten hinterlegt.</p>
        ) : (
          <ul aria-label="Begünstigte">
            {beneficiaries.map((name, index) => (
              <li key={index}>{name}</li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function Pipeline({
  baseHref,
  counts,
  emptyDescription,
  title,
}: {
  readonly baseHref: string;
  readonly counts: DashboardPipelineResponse;
  /** Du in the acquisition app, Sie in admin. */
  readonly emptyDescription: string;
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
            <a
              className={buttonClassName({ variant: "secondary" })}
              href={baseHref}
            >
              Akquise öffnen
            </a>
          }
          description={emptyDescription}
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
                  <Icon icon={ArrowRight} size={16} />
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
  figures,
  items,
}: {
  /** Key figures in their own disclosure before the definitions (admin). */
  readonly figures?: ReactNode;
  readonly items: ReadonlyArray<DashboardMetricDefinitionResponse>;
}) {
  return (
    <>
      {figures ? (
        <details className="dashboard-definitions">
          <summary>Weitere Kennzahlen</summary>
          {figures}
        </details>
      ) : null}
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
    </>
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
  const actionLabel =
    data.reminders.overdue > 0 || data.reminders.today > 0
      ? "Wiedervorlagen öffnen"
      : "Offene Sponsoren öffnen";

  return (
    <>
      <NextStep
        action={
          <a
            className={buttonClassName({ variant: "primary" })}
            href={nextHref}
          >
            <span className="btn-label">{actionLabel}</span>
            <Icon icon={ArrowRight} size={16} />
          </a>
        }
        consequence={
          <>
            {nextLabel}. {data.reminders.upcoming} weitere geplant ·{" "}
            {data.reminders.unscheduled} ohne Termin.
          </>
        }
        data-testid="dashboard-next-step"
        lead="Dein nächster Schritt:"
      />

      <div className="dashboard-personal-metrics">
        <a href={`${reminderHref}&urgency=overdue`}>
          <Icon icon={Clock} size={20} />
          <span>Überfällig</span>
          <strong>{data.reminders.overdue}</strong>
        </a>
        <a href={`${reminderHref}&urgency=today`}>
          <Icon icon={Clock} size={20} />
          <span>Heute</span>
          <strong>{data.reminders.today}</strong>
        </a>
        <a
          href={
            definition(dashboard, "acquirer.activities")?.href ??
            "/app/activities?view=contacts"
          }
        >
          <Icon icon={Activity} size={20} />
          <span>Dokumentiert</span>
          <strong>{data.activityCount}</strong>
        </a>
      </div>

      <Pipeline
        baseHref={pipelineHref}
        counts={data.pipeline}
        emptyDescription="Lege den ersten Sponsor an oder ordne einen bestehenden Kontakt zu."
        title="Deine persönliche Pipeline"
      />
    </>
  );
}

/** "Guten Morgen" before 11, "Guten Tag" until 18, then "Guten Abend" (Berlin). */
export function greeting(now: Date = new Date()) {
  const hour = Number(
    new Intl.DateTimeFormat("de-DE", {
      hour: "2-digit",
      hourCycle: "h23",
      timeZone: "Europe/Berlin",
    }).format(now),
  );
  return hour < 11 ? "Guten Morgen" : hour < 18 ? "Guten Tag" : "Guten Abend";
}

/** "noch 8 Tage bis zum Liefertag am Mittwoch, 11. November" (prototype). */
export function deliveryCountdown(startsAt: string, now: Date = new Date()) {
  const day = (value: Date) =>
    new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Berlin" }).format(
      value,
    );
  const start = new Date(startsAt);
  const days = Math.round(
    (Date.parse(day(start)) - Date.parse(day(now))) / 86_400_000,
  );
  const date = new Intl.DateTimeFormat("de-DE", {
    day: "numeric",
    month: "long",
    timeZone: "Europe/Berlin",
    weekday: "long",
  }).format(start);
  if (days <= 0) return `Liefertag heute, ${date}`;
  if (days === 1) return `morgen ist Liefertag, ${date}`;
  return `noch ${days} Tage bis zum Liefertag am ${date}`;
}

/** The prototype's "+12 % zur Vorwoche"; null without a previous week. */
export function weeklyChange(
  weeks: ReadonlyArray<{ readonly totalMinor: number }>,
): number | null {
  const last = weeks.at(-1)?.totalMinor;
  const previous = weeks.at(-2)?.totalMinor;
  if (last === undefined || !previous) return null;
  return Math.round(((last - previous) / previous) * 100);
}

function SparkBar({
  current,
  label,
  ratio,
}: {
  readonly current: boolean;
  readonly label: string;
  readonly ratio: number;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    ref.current?.style.setProperty("--bar", ratio.toFixed(3));
  }, [ratio]);
  return (
    <span
      className={current ? "spark-bar is-current" : "spark-bar"}
      ref={ref}
      title={label}
    />
  );
}

type QueueTone = "info" | "danger" | "warn";

interface QueueItem {
  readonly icon: LucideIcon;
  readonly count: number;
  readonly countLabel?: string;
  readonly label: string;
  readonly detail: string;
  readonly href: string;
  readonly tone: QueueTone;
}

const pipelineShapes: Readonly<
  Record<(typeof pipelineStages)[number][0], StatusShape>
> = {
  open: "draft",
  contacted: "open",
  committed: "done",
  declined: "cancelled",
  handedOver: "progress",
};

/**
 * New contact-form requests, from the inbox module. Only asked when the
 * server navigation lists the module for this account (switchable module).
 */
function useNewInquiries(
  client: LeonAidApiClient,
  identity: CurrentIdentityResponse,
) {
  const enabled = identity.navigation.some(
    (item) => item.key === "inbox" && item.surface === "web",
  );
  return useQuery({
    enabled,
    queryFn: () => client.listInboxCases({ status: "new", limit: 100 }),
    queryKey: ["dashboard", "inbox-new"],
    select: (cases) => ({
      count: cases.items.length,
      more: cases.nextOffset !== null,
    }),
  });
}

function AdminDashboard({
  client,
  dashboard,
  identity,
}: {
  readonly client: LeonAidApiClient;
  readonly dashboard: DashboardResponse;
  readonly identity: CurrentIdentityResponse;
}) {
  const inquiries = useNewInquiries(client, identity);
  const data = dashboard.charityAdmin;
  if (data === null) {
    return (
      <StatusMessage tone="error">
        <strong>Admin-Sicht nicht verfügbar</strong>
        <p>Für diese Aktion fehlt Ihre aktive Charity-Admin-Zuordnung.</p>
      </StatusMessage>
    );
  }
  const href = (key: string, fallback: string) =>
    definition(dashboard, key)?.href ?? fallback;
  const action = encodeURIComponent(dashboard.actionId);
  const ordersHref = `/admin/orders?action=${action}`;
  const pipelineHref = href("admin.pipeline", "/admin/acquisition");
  const { commitments, invoices } = data;
  const toReview = commitments.draft + commitments.reviewReady;

  const queue: QueueItem[] = [
    {
      icon: ShoppingBasket,
      count: toReview,
      label: "Bestellungen prüfen",
      detail: "Eingegangen oder prüfbereit",
      href: ordersHref,
      tone: "info" as const,
    },
    {
      icon: ReceiptEuro,
      count: invoices.overdue,
      label: "Überfällige Rechnungen",
      detail: `${formatMoney(invoices.overdueAmountMinor, invoices.currency)} offen`,
      href: href(
        "admin.overdue",
        `/admin/invoices?action=${action}&view=overdue`,
      ),
      tone: "danger" as const,
    },
    {
      icon: MailWarning,
      count: invoices.deliveryFailed,
      label: "Versand fehlgeschlagen",
      detail: "Rechnung erneut senden",
      href: href("admin.delivery_failed", `/admin/invoices?action=${action}`),
      tone: "danger" as const,
    },
    {
      icon: Inbox,
      count: inquiries.data?.count ?? 0,
      countLabel: inquiries.data?.more ? "100+" : undefined,
      label: "Neue Anfragen",
      detail: "Aus dem Kontaktformular",
      href: "/admin/inbox",
      tone: "info" as const,
    },
    {
      icon: ReceiptEuro,
      count: commitments.confirmed,
      label: "Rechnung erstellen",
      detail: "Bestätigt, noch ohne Rechnung",
      href: href("admin.to_invoice", ordersHref),
      tone: "warn" as const,
    },
  ].filter((item) => item.count > 0);

  const weeks = data.orderValueWeeks;
  const maxWeek = Math.max(1, ...weeks.map((week) => week.totalMinor));
  const lastWeek = weeks.at(-1);
  const change = weeklyChange(weeks);
  const { goal } = dashboard;
  const goalTarget =
    goal.targetValue === null ? null : Number(goal.targetValue);
  const goalActual = Number(goal.actualValue);
  const windows = data.delivery.enabled ? data.delivery.windows : [];
  const givenName = identity.displayName.split(" ")[0];

  return (
    <div className="dashboard" data-testid="admin-dashboard">
      <header className="page-header">
        <div>
          <div className="page-heading">
            <h1>
              {greeting()}, {givenName}
            </h1>
          </div>
          <p className="page-sub">
            {dashboard.actionName}
            {windows[0] ? ` · ${deliveryCountdown(windows[0].startsAt)}` : null}
          </p>
        </div>
        {toReview > 0 ? (
          <div className="page-actions">
            <a
              className={buttonClassName({ variant: "primary" })}
              data-testid="dashboard-primary-action"
              href={ordersHref}
            >
              <Icon icon={ShoppingBasket} size={16} />
              <span className="btn-label">{toReview} Bestellungen prüfen</span>
            </a>
          </div>
        ) : null}
      </header>

      <div className="dash-grid">
        <section aria-labelledby="queue-title" className="dash-queue">
          <h2 className="dash-h2" id="queue-title">
            Nächste Schritte
          </h2>
          {queue.length ? (
            <ol className="queue" data-testid="dashboard-queue">
              {queue.map((item) => (
                <li key={item.label}>
                  <a className="queue-item" href={item.href}>
                    <span
                      aria-hidden="true"
                      className={`queue-icon tone-${item.tone}`}
                    >
                      <Icon icon={item.icon} size={16} />
                    </span>
                    <span className="queue-text">
                      <span className="queue-label">{item.label}</span>
                      <span className="queue-detail">{item.detail}</span>
                    </span>
                    <span className="queue-count num">
                      {item.countLabel ?? item.count}
                    </span>
                    <Icon className="queue-arrow" icon={ArrowRight} size={16} />
                  </a>
                </li>
              ))}
            </ol>
          ) : (
            <p className="muted" data-testid="dashboard-queue-empty">
              Alles erledigt. Neue Aufgaben erscheinen hier, sobald etwas zu tun
              ist.
            </p>
          )}

          {data.delivery.enabled ? (
            <>
              <h2 className="dash-h2 dash-h2-gap">Lieferfenster</h2>
              {windows.length ? (
                <ul className="windows" data-testid="dashboard-windows">
                  {windows.map((window) => (
                    <li key={window.id}>
                      <a
                        className="window-row"
                        href={href(
                          "admin.delivery",
                          `/admin/orders?action=${action}&view=windows`,
                        )}
                      >
                        <Icon icon={Truck} size={14} />
                        <span className="window-label">
                          {snapshotWindowLabel({
                            startsAt: window.startsAt,
                            endsAt: window.endsAt,
                          })}
                        </span>
                        <span className="window-meter window-quantity">
                          {window.commitments
                            ? formatQuantities(window.quantities, 0)
                            : "noch frei"}
                        </span>
                        <span className="window-num num">
                          {window.commitments}{" "}
                          {window.commitments === 1
                            ? "Bestellung"
                            : "Bestellungen"}
                        </span>
                      </a>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">Keine kommenden Lieferfenster.</p>
              )}
            </>
          ) : null}
        </section>

        <aside aria-label="Kennzahlen der Aktion" className="dash-facts">
          <section className="fact" data-testid="dashboard-goal">
            <h2 className="dash-h2">Spendenziel</h2>
            <p className="fact-big num">
              {formatGoalValue(goal.actualValue, goal.unit, goal.currency)}{" "}
              {goalTarget !== null ? (
                <span className="fact-of">
                  von{" "}
                  {formatGoalValue(
                    goal.targetValue ?? "0",
                    goal.unit,
                    goal.currency,
                  )}
                </span>
              ) : null}
            </p>
            {goalTarget !== null ? (
              <Meter
                label="Fortschritt des Spendenziels"
                max={goalTarget}
                value={goalActual}
              />
            ) : null}
            <p className="fact-note" data-testid="goal-status">
              {goal.progressBasisPoints !== null &&
              goal.progressBasisPoints !== undefined
                ? `${Math.round(goal.progressBasisPoints / 100)} % erreicht`
                : "Noch kein Zielwert gepflegt"}
              {dashboard.beneficiaries.length
                ? ` · für ${new Intl.ListFormat("de-DE", {
                    type: "conjunction",
                  }).format(dashboard.beneficiaries)}`
                : null}
            </p>
          </section>

          <section className="fact" data-testid="dashboard-weekly">
            <h2 className="dash-h2">Bestellwert pro Woche</h2>
            <p className="fact-mid num">
              {formatMoney(lastWeek?.totalMinor ?? 0, commitments.currency)}
              {change !== null ? (
                <span className={change < 0 ? "trend is-down" : "trend is-up"}>
                  {change > 0 ? "+" : ""}
                  {change} % zur Vorwoche
                </span>
              ) : null}
            </p>
            <div
              aria-label={`Bestellwert der letzten ${weeks.length} Wochen, diese Woche ${formatMoney(
                lastWeek?.totalMinor ?? 0,
                commitments.currency,
              )}`}
              className="spark"
              role="img"
            >
              {weeks.map((week, index) => (
                <SparkBar
                  current={index === weeks.length - 1}
                  key={week.weekStart}
                  label={`KW ${week.isoWeek}: ${formatMoney(
                    week.totalMinor,
                    commitments.currency,
                  )}`}
                  ratio={week.totalMinor / maxWeek}
                />
              ))}
            </div>
            {weeks.length ? (
              <div aria-hidden="true" className="spark-axis">
                <span>KW {weeks[0]?.isoWeek}</span>
                <span>KW {lastWeek?.isoWeek}</span>
              </div>
            ) : null}
          </section>

          <section className="fact" data-testid="dashboard-pipeline">
            <h2 className="dash-h2">Sponsoren-Pipeline</h2>
            <ul className="pipeline">
              {pipelineStages.map(([key, label]) => (
                <li key={key}>
                  <a
                    className="pipeline-row"
                    href={`${pipelineHref}${pipelineHref.includes("?") ? "&" : "?"}status=${
                      key === "handedOver" ? "handed_over" : key
                    }`}
                  >
                    <StatusIcon label={label} status={pipelineShapes[key]} />
                    <span>{label}</span>
                    <span className="num pipeline-count">
                      {data.pipeline[key]}
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          </section>
        </aside>
      </div>
      <MetricDefinitions
        figures={
          <dl
            aria-label="Kennzahlen im Detail"
            className="dashboard-figures"
            data-testid="admin-dashboard-metrics"
          >
            <div>
              <dt>
                <a href={href("admin.commitments", ordersHref)}>Bestellungen</a>
              </dt>
              <dd>
                <strong className="num">{commitments.activeTotal}</strong>
                {formatQuantities(
                  commitments.quantities,
                  commitments.totalPieces,
                )}
              </dd>
            </div>
            <div>
              <dt>Bestellwert</dt>
              <dd>
                <strong className="num">
                  {formatMoney(
                    commitments.activeTotalMinor,
                    commitments.currency,
                  )}
                </strong>
                ohne stornierte Bestellungen
              </dd>
            </div>
            <div>
              <dt>
                <a
                  href={href(
                    "admin.invoiced",
                    `/admin/invoices?action=${action}`,
                  )}
                >
                  Fakturiert
                </a>
              </dt>
              <dd>
                <strong className="num">
                  {formatMoney(invoices.invoicedAmountMinor, invoices.currency)}
                </strong>
                ausgestellt, versendet oder bezahlt
              </dd>
            </div>
            <div>
              <dt>
                <a
                  href={href(
                    "admin.open_receivables",
                    `/admin/invoices?action=${action}&status=open`,
                  )}
                >
                  Offene Posten
                </a>
              </dt>
              <dd>
                <strong className="num">
                  {formatMoney(invoices.openAmountMinor, invoices.currency)}
                </strong>
                {invoices.open}{" "}
                {invoices.open === 1 ? "Rechnung" : "Rechnungen"}
              </dd>
            </div>
          </dl>
        }
        items={dashboard.metricDefinitions}
      />
    </div>
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
  useActionInUrl(actionId);
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
            : "Sobald Sie eine Charity-Aktion verwalten, erscheint hier der gemeinsame Arbeitsstand."
        }
        headingLevel={2}
        icon={Target}
        title="Noch keine passende Charity-Aktion"
      />
    );
  }

  const loading = (
    <div
      aria-label="Dashboard wird geladen"
      className="dashboard-loading"
      role="status"
    >
      <span />
      <p>Aktionsstand wird berechnet …</p>
    </div>
  );
  const failed = dashboard.isError ? (
    <StatusMessage tone="error">
      <strong>Aktionsstand nicht erreichbar</strong>
      <p>
        {
          actionErrorMessage(dashboard.error, {
            // The acquirer dashboard is the PWA (du); admins get Sie.
            address: mode === "acquirer" ? "du" : "Sie",
          }).message
        }
      </p>
      <Button onClick={() => void dashboard.refetch()} variant="secondary">
        Erneut laden
      </Button>
    </StatusMessage>
  ) : null;

  // Admin: the campaign comes from the rail switcher (?action=), as in the
  // prototype; the page has no picker of its own.
  if (mode === "charity_admin") {
    return dashboard.isPending ? (
      loading
    ) : dashboard.isError ? (
      failed
    ) : (
      <AdminDashboard
        client={client}
        dashboard={dashboard.data}
        identity={identity}
      />
    );
  }

  return (
    <div className="dashboard-page" data-dashboard-mode={mode}>
      <header className="dashboard-header">
        <div>
          <p>Dein Akquise-Tag</p>
          <h1>{`${greeting()}, ${identity.displayName.split(" ")[0]}.`}</h1>
          <span>Wiedervorlagen zuerst, Fortschritt immer im Blick.</span>
        </div>
        <label className="dashboard-action-picker">
          <span>Charity-Aktion</span>
          <select
            data-testid="dashboard-action"
            onChange={(event) => {
              setActionId(event.target.value);
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
        loading
      ) : dashboard.isError ? (
        failed
      ) : (
        <>
          <GoalProgress dashboard={dashboard.data} />
          <AcquirerDashboard dashboard={dashboard.data} />
          <MetricDefinitions items={dashboard.data.metricDefinitions} />
        </>
      )}
    </div>
  );
}
