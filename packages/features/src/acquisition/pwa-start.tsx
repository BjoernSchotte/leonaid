/*
 * "Start" of the acquisition app (prototype pwa/Acquire.tsx Start()):
 * greeting, the shared goal, today's follow-ups and the personal pipeline.
 */
import { Check, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

import type {
  AcquisitionActivityWorkItemResponse,
  CurrentIdentityResponse,
  DashboardResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import { EmptyState, Icon, Meter, StatusIcon } from "@leonaid/ui";

import {
  ASSIGNMENT_STATUSES,
  BoardFailed,
  BoardLoading,
  SponsorRow,
  assignmentStatusLabel,
  assignmentStatusShape,
  followInPage,
  followUpWhen,
  useSponsorBoard,
} from "./pwa-common";

const pipelineKey = {
  open: "open",
  contacted: "contacted",
  committed: "committed",
  declined: "declined",
  handed_over: "handedOver",
} as const;

function goalNumber(value: string) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatGoalValue(value: number, unit: string | null, currency: string) {
  if (unit === currency && /^[A-Z]{3}$/.test(currency)) {
    return new Intl.NumberFormat("de-DE", {
      currency,
      maximumFractionDigits: 2,
      style: "currency",
    }).format(value);
  }
  return `${new Intl.NumberFormat("de-DE", {
    maximumFractionDigits: 2,
  }).format(value)}${unit ? ` ${unit}` : ""}`;
}

/** The goal card; `goal-status` keeps the spoken summary of 6.3. */
export function AcquirerGoal({
  dashboard,
}: {
  readonly dashboard: DashboardResponse;
}) {
  const { goal } = dashboard;
  const actualNumber = goalNumber(goal.actualValue) ?? 0;
  const targetNumber =
    goal.targetValue === null ? null : goalNumber(goal.targetValue);
  const actual = formatGoalValue(actualNumber, goal.unit, goal.currency);
  const target =
    targetNumber === null
      ? null
      : formatGoalValue(targetNumber, goal.unit, goal.currency);
  const percentage =
    goal.progressBasisPoints === null || goal.progressBasisPoints === undefined
      ? null
      : goal.progressBasisPoints / 100;
  const spoken =
    target === null || percentage === null
      ? `Aktionsstand: ${actual}. Ein Zielwert ist noch nicht vollständig gepflegt.`
      : `Aktionsziel: ${actual} von ${target} erreicht, ${new Intl.NumberFormat(
          "de-DE",
          { maximumFractionDigits: 2 },
        ).format(percentage)} Prozent.`;
  const remaining =
    targetNumber === null ? null : Math.max(0, targetNumber - actualNumber);
  return (
    <section
      aria-labelledby="goal-title"
      className="pwa-card"
      data-configured={goal.configured}
      data-testid="dashboard-goal"
    >
      <h2 className="pwa-h2" id="goal-title">
        Gemeinsames Ziel
      </h2>
      <p className="goal-value num">
        {actual}
        {target ? <span className="goal-of"> von {target}</span> : null}
      </p>
      {percentage === null ? (
        <p className="small muted">
          Sobald Zielwert und Einheit gepflegt sind, zeigt LeonAid hier den
          Fortschritt.
        </p>
      ) : (
        <>
          <Meter
            label="Fortschritt des Aktionsziels"
            max={10_000}
            value={Math.min(goal.progressBasisPoints ?? 0, 10_000)}
          />
          <p className="small muted">
            {remaining === 0
              ? "Das Ziel ist erreicht."
              : `Noch ${formatGoalValue(remaining ?? 0, goal.unit, goal.currency)} bis zum Ziel.`}
          </p>
        </>
      )}
      <p className="sr-only" data-testid="goal-status">
        {spoken}
      </p>
    </section>
  );
}

function DueToday({
  actionId,
  identity,
  items,
}: {
  readonly actionId: string;
  readonly identity: CurrentIdentityResponse;
  readonly items: ReadonlyArray<AcquisitionActivityWorkItemResponse>;
}) {
  const due = items
    .filter(
      (item) =>
        item.dueAt && (item.urgency === "overdue" || item.urgency === "today"),
    )
    .sort((a, b) => (a.dueAt ?? "").localeCompare(b.dueAt ?? ""));
  return due.length ? (
    <ul className="pwa-list" data-testid="due-today">
      {due.map((item) => (
        <SponsorRow
          actionId={actionId}
          item={item}
          key={item.assignmentId}
          meta={`Wiedervorlage ${followUpWhen(item)}`}
          userId={identity.userId}
        />
      ))}
    </ul>
  ) : (
    <EmptyState
      description="Plane Wiedervorlagen direkt nach einem Gespräch, dann erscheinen sie hier."
      icon={Check}
      title="Heute ist nichts fällig"
    />
  );
}

export function AcquirerStart({
  actionId,
  choice,
  client,
  dashboard,
  definitions,
  identity,
}: {
  readonly actionId: string;
  /** The campaign choice for acquirers in several campaigns. */
  readonly choice: ReactNode;
  readonly client: LeonAidApiClient;
  readonly dashboard: DashboardResponse;
  /** "So werden die Kennzahlen berechnet" (6.3, kept). */
  readonly definitions: ReactNode;
  readonly identity: CurrentIdentityResponse;
}) {
  const board = useSponsorBoard(client, actionId);
  const action = encodeURIComponent(actionId);
  const pipeline = dashboard.acquirer?.pipeline;
  return (
    <>
      {choice}
      <AcquirerGoal dashboard={dashboard} />

      <section aria-labelledby="due-title">
        <div className="pwa-section-head">
          <h2 className="pwa-h2" id="due-title">
            Heute dran
          </h2>
          <a
            className="pwa-more"
            href={`/app/activities?view=contacts&action=${action}`}
            onClick={followInPage}
          >
            Alle Wiedervorlagen
          </a>
        </div>
        {board.isPending ? (
          <BoardLoading label="Wiedervorlagen werden geladen" />
        ) : board.isError ? (
          <BoardFailed
            onRetry={() => void board.refetch()}
            title="Wiedervorlagen nicht erreichbar"
          />
        ) : (
          <DueToday
            actionId={actionId}
            identity={identity}
            items={board.data.workItems}
          />
        )}
      </section>

      {pipeline ? (
        <section aria-labelledby="pipe-title" data-testid="dashboard-pipeline">
          <h2 className="pwa-h2" id="pipe-title">
            Deine persönliche Pipeline
          </h2>
          <ul className="pipe">
            {ASSIGNMENT_STATUSES.map((status) => {
              const label = assignmentStatusLabel[status];
              return (
                <li key={status}>
                  <a
                    className="pipe-row"
                    href={`/app/sponsors?action=${action}&status=${status}`}
                    onClick={followInPage}
                  >
                    {/* Decorative: the word follows. */}
                    <StatusIcon
                      label=""
                      size={16}
                      status={assignmentStatusShape[status]}
                    />
                    <span className="pipe-label">{label}</span>
                    <span className="pipe-count num">
                      {pipeline[pipelineKey[status]]}
                    </span>
                    <Icon icon={ChevronRight} size={16} />
                  </a>
                </li>
              );
            })}
            {pipeline.handedOver > 0 ? (
              <li>
                <span className="pipe-row" data-testid="pipeline-handed-over">
                  <StatusIcon
                    label=""
                    size={16}
                    status={assignmentStatusShape.handed_over}
                  />
                  <span className="pipe-label">
                    {assignmentStatusLabel.handed_over}
                    <span className="pipe-note">
                      nicht mehr in deiner Liste
                    </span>
                  </span>
                  <span className="pipe-count num">{pipeline.handedOver}</span>
                </span>
              </li>
            ) : null}
          </ul>
        </section>
      ) : null}
      {definitions}
    </>
  );
}
