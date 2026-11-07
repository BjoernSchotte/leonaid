/*
 * Shared parts of the acquirer screens in the PWA (prototype
 * pwa/Acquire.tsx): status words and shapes, the sponsor row, the
 * campaign choice and the sponsor list query.
 */
import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { useCallback, useMemo, useState, type MouseEvent } from "react";

import type {
  AcquisitionActivityWorkItemResponse,
  CurrentIdentityResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Button,
  Field,
  Icon,
  Select,
  StatusIcon,
  StatusMessage,
  SkeletonRows,
  type StatusShape,
} from "@leonaid/ui";

import { navigateInPage } from "../shared/location";
import { relativeDay } from "../shared/dates";
import { PWA_BASE, pwaHref } from "@leonaid/ui/base-paths";

export type AssignmentStatus = AcquisitionActivityWorkItemResponse["status"];

/**
 * The states a sponsor in the acquirer's list can have, in pipeline order.
 * A handed-over sponsor leaves the list (the board omits it), so
 * "Übergeben" is no filter; Start shows its count without a link.
 */
export const ASSIGNMENT_STATUSES: readonly AssignmentStatus[] = [
  "open",
  "contacted",
  "committed",
  "declined",
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
    <Field label="Charity-Aktion">
      <Select
        data-testid="acquirer-action"
        id="acquirer-action"
        onChange={(event) => onChange(event.target.value)}
        value={actionId}
      >
        {memberships.map((membership) => (
          <option key={membership.actionId} value={membership.actionId}>
            {membership.actionName}
          </option>
        ))}
      </Select>
    </Field>
  );
}

/** The acquirer's sponsors with follow-ups and recent contacts. */
export function useSponsorBoard(client: LeonAidApiClient, actionId: string) {
  return useQuery({
    enabled: Boolean(actionId),
    // All of the acquirer's sponsors; `limit` caps only the latest contacts
    // across all sponsors (the detail's "Verlauf" shows those).
    queryFn: () => client.getAcquisitionActivityBoard(actionId, { limit: 100 }),
    queryKey: ["acquisition-activity-board", actionId],
  });
}

export function sponsorHref(actionId: string, assignmentId: string) {
  return `${PWA_BASE}sponsors?action=${encodeURIComponent(actionId)}&assignment=${encodeURIComponent(assignmentId)}`;
}

/*
 * Focus after an in-page screen change: the activated link unmounts, so the
 * new screen's heading takes the focus (and is announced). Only screen
 * changes ask for it, not filter changes or the first page load.
 */
// A request expires: a heading that mounts later (another screen, a
// re-render after a slow query) never takes the focus unasked.
const HEADING_FOCUS_WINDOW_MS = 1500;
let headingFocusUntil = 0;

/** Shows another acquirer screen without a page load; its h1 gets focus. */
export function navigateToScreen(
  href: string,
  { replace = false }: { readonly replace?: boolean } = {},
) {
  headingFocusUntil = performance.now() + HEADING_FOCUS_WINDOW_MS;
  navigateInPage(href, { replace });
  window.scrollTo({ top: 0 });
}

/** Ref for a screen's h1 (with tabIndex -1): focused after navigateToScreen. */
export function useScreenHeading() {
  return useCallback((element: HTMLElement | null) => {
    if (!element) return;
    const requested = performance.now() <= headingFocusUntil;
    // One request, one heading: the first heading that mounts consumes it.
    headingFocusUntil = 0;
    if (requested) element.focus({ preventScroll: true });
  }, []);
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
  navigateToScreen(event.currentTarget.getAttribute("href") ?? pwaHref());
}

/** "tel:" wants the number without spaces or separators (RFC 3966). */
export function telHref(phone: string) {
  return `tel:${phone.replace(/[^\d+]/g, "")}`;
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
  href,
  item,
  meta,
  userId,
}: {
  readonly actionId: string;
  /** Target of the row; the sponsor's detail by default. */
  readonly href?: string;
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
        href={href ?? sponsorHref(actionId, item.assignmentId)}
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
