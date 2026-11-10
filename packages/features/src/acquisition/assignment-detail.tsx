import { useQuery } from "@tanstack/react-query";

import type {
  AcquisitionActivityWorkItemResponse,
  AcquisitionAssignmentHistoryResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Button,
  DetailProps,
  DetailSection,
  DetailTimeline,
  StatusMessage,
} from "@leonaid/ui";

import { formatDate, formatDateTime } from "../shared/dates";

/*
 * The detail of one assignment in the web pipeline: the sponsor's place and
 * contact from the board row, and who is responsible, the next step and the
 * history from the assignment itself.
 */

export const assignmentStatusLabels = {
  committed: "Zugesagt",
  contacted: "Kontaktiert",
  declined: "Abgesagt",
  handed_over: "Übergeben",
  open: "Offen",
} as const;

type AssignmentStatus = keyof typeof assignmentStatusLabels;

function statusOf(state: Record<string, unknown>): AssignmentStatus | null {
  const value = state.status;
  return typeof value === "string" && value in assignmentStatusLabels
    ? (value as AssignmentStatus)
    : null;
}

function textOf(state: Record<string, unknown>, key: string): string | null {
  const value = state[key];
  return typeof value === "string" && value ? value : null;
}

/** One history entry in words: what changed, most important change first. */
export function historyText(
  entry: Pick<
    AcquisitionAssignmentHistoryResponse,
    "newState" | "previousState"
  >,
): string {
  const before = statusOf(entry.previousState);
  const after = statusOf(entry.newState);
  if (!before) {
    return after && after !== "open"
      ? `Zuordnung angelegt (${assignmentStatusLabels[after]})`
      : "Zuordnung angelegt";
  }
  if (after && before !== after) {
    return before === "handed_over"
      ? `Zuordnung wieder aufgenommen (${assignmentStatusLabels[after]})`
      : `Status: ${assignmentStatusLabels[before]} → ${assignmentStatusLabels[after]}`;
  }
  const step = textOf(entry.newState, "nextAction");
  if (step !== textOf(entry.previousState, "nextAction")) {
    return step ? `Nächster Schritt: ${step}` : "Nächsten Schritt entfernt";
  }
  const due = textOf(entry.newState, "dueAt");
  if (due !== textOf(entry.previousState, "dueAt")) {
    return due ? `Fällig am ${formatDate(due)}` : "Termin entfernt";
  }
  if (entry.newState.priority !== entry.previousState.priority) {
    return "Priorität geändert";
  }
  return "Zuordnung geändert";
}

export interface AssignmentDetailProps {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  readonly item: AcquisitionActivityWorkItemResponse;
}

export function AssignmentDetail({
  actionId,
  client,
  item,
}: AssignmentDetailProps) {
  const details = useQuery({
    queryFn: () => client.getAcquisitionAssignment(actionId, item.assignmentId),
    queryKey: ["acquisition-assignment", actionId, item.assignmentId],
  });
  const blocked = (channel: "email" | "phone") =>
    item.suppressedChannels.includes(channel) ? " (Kontaktsperre)" : "";
  return (
    <div
      className="acq-admin-detail"
      data-assignment-id={item.assignmentId}
      data-testid="acquisition-assignment-detail"
    >
      <DetailSection title="Sponsor">
        <DetailProps
          items={[
            {
              label: "Ort",
              value:
                [item.postalCode, item.city].filter(Boolean).join(" ") ||
                "Nicht gepflegt",
            },
            {
              label: "Ansprechperson",
              value: item.contactName ?? "Nicht gepflegt",
            },
            {
              label: "E-Mail",
              value: item.email
                ? `${item.email}${blocked("email")}`
                : "Nicht gepflegt",
            },
            {
              label: "Telefon",
              value: item.phone
                ? `${item.phone}${blocked("phone")}`
                : "Nicht gepflegt",
            },
          ]}
        />
      </DetailSection>
      <DetailSection title="Zuordnung">
        <DetailProps
          items={[
            {
              label: "Akquisiteur",
              value:
                details.data?.assignment.acquirerDisplayName ??
                item.assignedAcquirers
                  .map((person) => person.displayName)
                  .join(", "),
            },
            { label: "Status", value: assignmentStatusLabels[item.status] },
            {
              label: "Nächster Schritt",
              value: item.nextAction ?? "Noch nicht geplant",
            },
            {
              label: "Fällig",
              value: item.dueAt ? formatDate(item.dueAt) : "Nicht terminiert",
            },
          ]}
        />
      </DetailSection>
      <DetailSection title="Verlauf">
        {details.isPending ? (
          <p aria-live="polite" role="status">
            Verlauf wird geladen
          </p>
        ) : details.isError ? (
          <StatusMessage tone="error">
            <p>Der Verlauf konnte nicht geladen werden.</p>
            <Button onClick={() => void details.refetch()} variant="secondary">
              Erneut laden
            </Button>
          </StatusMessage>
        ) : (
          <DetailTimeline
            items={[...details.data.history].reverse().map((entry) => ({
              dateTime: entry.changedAt,
              id: entry.id,
              text: historyText(entry),
              time: `${formatDateTime(entry.changedAt)} · ${entry.changedByDisplayName}`,
            }))}
          />
        )}
      </DetailSection>
    </div>
  );
}
