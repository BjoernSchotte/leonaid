/*
 * The minimal read cache of the acquisition PWA (specs/pwa-offline-queue
 * §8.2): what an offline capture needs and nothing more. Street addresses,
 * postal codes, other acquirers' names, the activity feed and invoice data
 * never reach the device; contact fields only for the acquirer's own
 * assigned sponsors (D2).
 */
import type {
  AcquisitionActivityBoardResponse,
  AcquisitionActivityWorkItemResponse,
  CommitmentCaptureContextResponse,
  CurrentIdentityResponse,
} from "@leonaid/api-client";

const DAY_MS = 86_400_000;
/** Older read-cache documents are not shown; capture is blocked (D3). */
export const READ_CACHE_SHOW_DAYS = 7;
/** Older read-cache documents are deleted (§8.5). */
export const READ_CACHE_KEEP_DAYS = 14;

export type CacheFreshness = "fresh" | "stale" | "expired";

export function cacheFreshness(
  fetchedAt: string,
  now: Date = new Date(),
): CacheFreshness {
  const fetched = Date.parse(fetchedAt);
  // A fetch time in the future (clock moved back) counts as stale, so the
  // acquirer refreshes instead of working on a list of unknown age.
  if (!Number.isFinite(fetched) || fetched > now.getTime() + 5 * 60_000) {
    return "stale";
  }
  const age = now.getTime() - fetched;
  if (age > READ_CACHE_KEEP_DAYS * DAY_MS) return "expired";
  if (age > READ_CACHE_SHOW_DAYS * DAY_MS) return "stale";
  return "fresh";
}

function minimizeWorkItem(
  item: AcquisitionActivityWorkItemResponse,
): AcquisitionActivityWorkItemResponse {
  return {
    assignedAcquirers: [],
    assignmentId: item.assignmentId,
    city: item.city,
    contactName: item.contactName,
    dueAt: item.dueAt,
    email: item.email,
    nextAction: item.nextAction,
    partyDisplayName: item.partyDisplayName,
    partyId: item.partyId,
    partyKind: item.partyKind,
    phone: item.phone,
    postalCode: null,
    priority: item.priority,
    revision: item.revision,
    status: item.status,
    suppressedChannels: [...item.suppressedChannels],
    urgency: item.urgency,
  };
}

/** The sponsor list as the device keeps it: own sponsors, no feed. */
export function minimizeBoard(
  board: AcquisitionActivityBoardResponse,
): AcquisitionActivityBoardResponse {
  return {
    actionId: board.actionId,
    activities: [],
    generatedAt: board.generatedAt,
    workItems: board.workItems
      .filter((item) => item.status !== "handed_over")
      .map(minimizeWorkItem),
  };
}

/** Offerings and delivery windows: no personal data, kept as served. */
export function minimizeCaptureContext(
  context: CommitmentCaptureContextResponse,
): CommitmentCaptureContextResponse {
  return {
    actionId: context.actionId,
    actionName: context.actionName,
    deliveryConfiguration: context.deliveryConfiguration ?? null,
    offerings: context.offerings.map((offering) => ({ ...offering })),
  };
}

/**
 * The identity summary of the `meta` store (§8.1): enough to render the
 * shell and bind the queue to the user. Core checks the session and
 * membership again at every send. The user's own e-mail address is not
 * kept; only acquirer memberships (driver ones too while the device keeps
 * the tour) and the PWA's own navigation are.
 */
export interface IdentitySummary {
  readonly userId: string;
  readonly displayName: string;
  readonly clubName: string;
  readonly roleLabels: readonly string[];
  readonly memberships: CurrentIdentityResponse["actionMemberships"];
  readonly navigation: CurrentIdentityResponse["navigation"];
  readonly landingPath: string;
  readonly sessionExpiresAt: string;
  readonly savedAt: string;
}

export function summarizeIdentity(
  identity: CurrentIdentityResponse,
  now: Date = new Date(),
  {
    drivers = false,
  }: {
    /** The device keeps the driver's tour (both flags on, D14 g). */
    readonly drivers?: boolean;
  } = {},
): IdentitySummary {
  return {
    userId: identity.userId,
    displayName: identity.displayName,
    clubName: identity.installation.clubName,
    roleLabels: [...identity.roleLabels],
    memberships: identity.actionMemberships
      .filter(
        (membership) =>
          membership.role === "acquirer" ||
          (drivers && membership.role === "driver"),
      )
      .map((membership) => ({ ...membership })),
    navigation: identity.navigation
      .filter((item) => item.surface === "pwa")
      .map((item) => ({ ...item })),
    landingPath: identity.landingPath,
    sessionExpiresAt: identity.sessionExpiresAt,
    savedAt: now.toISOString(),
  };
}

/** The shell's identity offline; the server values are never invented. */
export function identityFromSummary(
  summary: IdentitySummary,
): CurrentIdentityResponse {
  return {
    actionMemberships: [...summary.memberships],
    displayName: summary.displayName,
    email: "",
    freshLoginAt: summary.savedAt,
    freshUntil: summary.savedAt,
    globalRoles: [],
    installation: { clubName: summary.clubName },
    landingPath: summary.landingPath,
    navigation: [...summary.navigation],
    preferredSurface: null,
    roleLabels: [...summary.roleLabels],
    sessionExpiresAt: summary.sessionExpiresAt,
    sessionLastSeenAt: summary.savedAt,
    userId: summary.userId,
  };
}

/** A cached session that has ended is no ground for an offline start. */
export function sessionEnded(
  summary: IdentitySummary,
  now: Date = new Date(),
): boolean {
  const expires = Date.parse(summary.sessionExpiresAt);
  return !Number.isFinite(expires) || expires <= now.getTime();
}
