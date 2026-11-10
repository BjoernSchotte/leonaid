/*
 * The acquirer's choices for a queued capture Core refused
 * (specs/pwa-offline-queue §10). A choice that changes the content gives
 * the entry a new body and a new key (§9.3); `allowFullWindow` is not in
 * Core's hash, so "Trotzdem eintragen" keeps the key (§10.2).
 */
import type {
  CommitmentCaptureContextResponse,
  CreateCommitmentRequest,
  DeliveryWindowResponse,
} from "@leonaid/api-client";

import {
  isTourEntry,
  type ActivityEntry,
  type CommitmentEntry,
  type QueueEntry,
} from "./queue";

export type Resolution =
  | "keep-follow-up"
  | "discard-follow-up"
  | "keep-status"
  | "discard-status"
  | "as-visit"
  | "copy-note"
  | "book-anyway"
  | "other-window"
  | "as-draft"
  | "accept-price"
  | "complete-delivery"
  | "discard";

/** The choices of §10 for an entry, in the order the sheet shows them. */
export function resolutionsFor(entry: QueueEntry): Resolution[] {
  // A driver's mark or order (krapfentaxi-touren §9): Core's state wins,
  // the driver marks again on it; no acquirer choice applies.
  if (isTourEntry(entry)) return ["discard"];
  const code = entry.lastError?.code ?? "";
  const note = entry.kind === "activity" && Boolean(entry.request.note);
  if (entry.state === "expired" || entry.state === "blocked") {
    return note ? ["copy-note", "discard"] : ["discard"];
  }
  if (entry.state !== "conflict") return ["discard"];
  switch (code) {
    case "follow_up_not_applied":
      return ["keep-follow-up", "discard-follow-up"];
    case "status_not_applied":
      return ["keep-status", "discard-status"];
    case "contact_suppressed":
      return ["as-visit", "discard"];
    case "sponsor_not_assigned":
      return note ? ["copy-note", "discard"] : ["discard"];
    case "delivery_window_full":
      return ["book-anyway", "other-window", "as-draft", "discard"];
    case "delivery_window_unavailable":
      return ["other-window", "as-draft", "discard"];
    case "commitment_price_changed":
      return ["accept-price", "discard"];
    case "delivery_required":
    case "delivery_address_required":
    case "delivery_window_required":
      return ["complete-delivery", "as-draft", "discard"];
    default:
      return note ? ["copy-note", "discard"] : ["discard"];
  }
}

export const resolutionLabel: Readonly<Record<Resolution, string>> = {
  "keep-follow-up": "Meine Wiedervorlage übernehmen",
  "discard-follow-up": "Die andere Wiedervorlage behalten",
  "keep-status": "Meinen Stand übernehmen",
  "discard-status": "Den anderen Stand behalten",
  "as-visit": "Als Besuch speichern",
  "copy-note": "Notiz kopieren",
  "book-anyway": "Trotzdem eintragen",
  "other-window": "Anderes Fenster wählen",
  "as-draft": "Als Entwurf speichern",
  "accept-price": "Neuen Preis übernehmen",
  "complete-delivery": "Ergänzen",
  discard: "Verwerfen",
};

/** "Als Besuch speichern": the contact goes in person (new key). */
export function asVisit(entry: ActivityEntry): ActivityEntry {
  return { ...entry, request: { ...entry.request, channel: "in_person" } };
}

/** "Trotzdem eintragen": the same body with the confirmation, same key. */
export function bookAnyway(entry: CommitmentEntry): CommitmentEntry {
  return {
    ...entry,
    base: { ...entry.base, windowFullyBooked: true },
    request: { ...entry.request, allowFullWindow: true },
  };
}

/** "Als Entwurf speichern": no delivery check and no window guard. */
export function asDraft(entry: CommitmentEntry): CommitmentEntry {
  return {
    ...entry,
    request: {
      ...entry.request,
      allowFullWindow: false,
      readyForReview: false,
    },
  };
}

/** "Anderes Fenster wählen". */
export function withWindow(
  entry: CommitmentEntry,
  window: DeliveryWindowResponse,
): CommitmentEntry {
  return {
    ...entry,
    base: {
      ...entry.base,
      windowFullyBooked: window.fullyBooked,
      windowId: window.id,
    },
    request: {
      ...entry.request,
      allowFullWindow: window.fullyBooked,
      deliveryWindowId: window.id,
    },
  };
}

/** "Ergänzen": the delivery address and window Core now requires. */
export function withDelivery(
  entry: CommitmentEntry,
  delivery: Required<
    Pick<CreateCommitmentRequest, "deliveryRecipient" | "deliveryWindowId">
  >,
  window: DeliveryWindowResponse,
): CommitmentEntry {
  return withWindow(
    {
      ...entry,
      request: {
        ...entry.request,
        deliveryRecipient: delivery.deliveryRecipient,
        deliveryWindowId: delivery.deliveryWindowId,
      },
    },
    window,
  );
}

interface PriceDetails {
  readonly lines?: ReadonlyArray<{
    readonly offeringId?: string;
    readonly unitPriceMinor?: number;
  }>;
}

/** "Neuen Preis übernehmen": Core's prices as the new quote (§11.3). */
export function acceptPrice(entry: CommitmentEntry): CommitmentEntry | null {
  const details = (entry.lastError?.details ?? {}) as PriceDetails;
  const prices = new Map(
    (details.lines ?? []).flatMap((line) =>
      line.offeringId && typeof line.unitPriceMinor === "number"
        ? [[line.offeringId, line.unitPriceMinor] as const]
        : [],
    ),
  );
  if (!entry.request.lines.every((line) => prices.has(line.offeringId))) {
    return null;
  }
  const lines = entry.request.lines.map((line) => ({
    ...line,
    quotedUnitPriceMinor: prices.get(line.offeringId)!,
  }));
  return {
    ...entry,
    base: { ...entry.base, unitPriceMinor: lines[0]?.quotedUnitPriceMinor },
    request: { ...entry.request, lines },
  };
}

/** Windows the acquirer can still choose (not retired, not started). */
export function choosableWindows(
  context: CommitmentCaptureContextResponse | null | undefined,
  now: Date = new Date(),
): DeliveryWindowResponse[] {
  return (context?.deliveryConfiguration?.windows ?? []).filter(
    (window) => !window.retired && Date.parse(window.startsAt) > now.getTime(),
  );
}

/**
 * §10.3: the refreshed read cache shows the chosen window as full; the
 * entry asks before it is sent at all. Null when nothing stands against
 * sending.
 */
export function preflightConflict(
  entry: QueueEntry,
  context: CommitmentCaptureContextResponse | null | undefined,
): string | null {
  if (entry.kind !== "commitment" || !context) return null;
  const request = entry.request;
  if (!request.readyForReview || request.allowFullWindow) return null;
  const windowId = request.deliveryWindowId;
  if (!windowId) return null;
  const window = context.deliveryConfiguration?.windows.find(
    (item) => item.id === windowId,
  );
  if (!window) return null;
  if (window.retired) return "delivery_window_unavailable";
  return window.fullyBooked ? "delivery_window_full" : null;
}
