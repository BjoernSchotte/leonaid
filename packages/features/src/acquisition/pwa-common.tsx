/*
 * Shared parts of the acquirer screens in the PWA (prototype
 * pwa/Acquire.tsx): status words and shapes, the sponsor row, the
 * campaign choice and the sponsor list query.
 */
import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { useMemo, useState, type MouseEvent } from "react";

import type {
  AcquisitionActivityWorkItemResponse,
  CurrentIdentityResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Button,
  Icon,
  StatusIcon,
  StatusMessage,
  SkeletonRows,
  type StatusShape,
} from "@leonaid/ui";

import { navigateInPage } from "../shared/location";
import { relativeDay } from "../shared/dates";

export type AssignmentStatus = AcquisitionActivityWorkItemResponse["status"];

/** The server's assignment states, in pipeline order. */
export const ASSIGNMENT_STATUSES: readonly AssignmentStatus[] = [
  "open",
  "contacted",
  "committed",
  "declined",
  "handed_over",
];

export const assignmentStatusLabel: Readonly<Record<AssignmentStatus, string>> =
  {
    open: "Offen",
    contacted: "Kontaktiert",
    committed: "Zugesagt",
    declined: "Abgesagt",
    handed_over: "Übergeben",
  };

/** Same shapes as the admin pipeline (dashboard.tsx pipelineShapes). */
export const assignmentStatusShape: Readonly<
  Record<AssignmentStatus, StatusShape>
> = {
  open: "draft",
  contacted: "open",
  committed: "done",
  declined: "cancelled",
  handed_over: "progress",
};

export function isAssignmentStatus(
  value: string | null,
): value is AssignmentStatus {
  return ASSIGNMENT_STATUSES.includes(value as AssignmentStatus);
}

/** The acquirer's campaigns; ?action= picks one, else the first. */
export function useAcquirerAction(identity: CurrentIdentityResponse) {
  const memberships = useMemo(
    () => [
      ...new Map(
        identity.actionMemberships
          .filter((membership) => membership.role === "acquirer")
          .map((membership) => [membership.actionId, membership]),
      ).values(),
    ],
    [identity.actionMemberships],
  );
  const requested = new URLSearchParams(window.location.search).get("action");
  const [actionId, setActionId] = useState(
    memberships.find((item) => item.actionId === requested)?.actionId ??
      memberships[0]?.actionId ??
      "",
  );
  function choose(next: string) {
    setActionId(next);
    const url = new URL(window.location.href);
    url.searchParams.set("action", next);
    navigateInPage(`${url.pathname}${url.search}`, { replace: true });
  }
  return { actionId, memberships, choose } as const;
}

/**
 * Shown only for an acquirer in several campaigns: the app bar names one
 * campaign, and the prototype has a single one.
 */
export function ActionChoice({
  actionId,
  memberships,
  onChange,
}: {
  readonly actionId: string;
  readonly memberships: ReadonlyArray<{
    readonly actionId: string;
    readonly actionName: string;
  }>;
  readonly onChange: (actionId: string) => void;
}) {
  if (memberships.length < 2) return null;
  return (
    <label className="pwa-action-choice">
      <span>Charity-Aktion</span>
      <select
        className="input select"
        data-testid="acquirer-action"
        onChange={(event) => onChange(event.target.value)}
        value={actionId}
      >
        {memberships.map((membership) => (
          <option key={membership.actionId} value={membership.actionId}>
            {membership.actionName}
          </option>
        ))}
      </select>
    </label>
  );
}

/** The acquirer's sponsors with follow-ups and recent contacts. */
export function useSponsorBoard(client: LeonAidApiClient, actionId: string) {
  return useQuery({
    enabled: Boolean(actionId),
    // The server returns at most 100 sponsors and the latest contacts.
    queryFn: () => client.getAcquisitionActivityBoard(actionId, { limit: 100 }),
    queryKey: ["acquisition-activity-board", actionId],
  });
}

export function sponsorHref(actionId: string, assignmentId: string) {
  return `/app/sponsors?action=${encodeURIComponent(actionId)}&assignment=${encodeURIComponent(assignmentId)}`;
}

/** In-page link: the shell keeps its state and the tabs follow. */
export function followInPage(event: MouseEvent<HTMLAnchorElement>) {
  if (
    event.defaultPrevented ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  ) {
    return;
  }
  event.preventDefault();
  navigateInPage(event.currentTarget.getAttribute("href") ?? "/app/");
  window.scrollTo({ top: 0 });
}

export function otherAcquirers(
  item: AcquisitionActivityWorkItemResponse,
  userId: string,
) {
  return item.assignedAcquirers
    .filter((assignee) => assignee.userId !== userId)
    .map((assignee) => assignee.displayName);
}

/** "Heute", "Morgen", "vor 3 Tagen" for a follow-up; null without one. */
export function followUpWhen(item: AcquisitionActivityWorkItemResponse) {
  return item.dueAt ? relativeDay(item.dueAt) : null;
}

export function SponsorRow({
  actionId,
  item,
  meta,
  userId,
}: {
  readonly actionId: string;
  readonly item: AcquisitionActivityWorkItemResponse;
  readonly meta?: string;
  readonly userId: string;
}) {
  const label = assignmentStatusLabel[item.status];
  const others = otherAcquirers(item, userId);
  const detail =
    meta ?? [label, item.contactName ?? item.city].filter(Boolean).join(" · ");
  return (
    <li>
      <a
        className="pwa-row"
        data-party-id={item.partyId}
        data-party-kind={item.partyKind}
        data-testid="sponsor-row"
        href={sponsorHref(actionId, item.assignmentId)}
        onClick={followInPage}
      >
        {/* The status word is in the meta line unless a meta replaces it;
            an empty label keeps the shape decorative next to the word. */}
        <StatusIcon
          label={meta ? label : ""}
          size={16}
          status={assignmentStatusShape[item.status]}
        />
        <span className="pwa-row-text">
          <span className="pwa-row-title">{item.partyDisplayName}</span>
          <span className="pwa-row-meta">
            {detail}
            {others.length ? (
              <span data-testid="co-assignees">
                {` · mit ${others.join(", ")}`}
              </span>
            ) : null}
          </span>
        </span>
        <span className="pwa-row-chevron">
          <Icon icon={ChevronRight} size={18} />
        </span>
      </a>
    </li>
  );
}

export function BoardLoading({ label }: { readonly label: string }) {
  return (
    <div aria-label={label} role="status">
      <SkeletonRows rows={4} />
    </div>
  );
}

export function BoardFailed({
  onRetry,
  retryLabel = "Erneut laden",
  title,
}: {
  readonly onRetry: () => void;
  readonly retryLabel?: string;
  readonly title: string;
}) {
  return (
    <StatusMessage tone="error">
      <div>
        <strong>{title}</strong>
        <p>
          Prüfe deine Verbindung. Bereits geöffnete Daten werden nicht offline
          verändert.
        </p>
        <Button onClick={onRetry} variant="secondary">
          {retryLabel}
        </Button>
      </div>
    </StatusMessage>
  );
}
