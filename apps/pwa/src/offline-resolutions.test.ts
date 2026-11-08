/*
 * The acquirer's choices of specs/pwa-offline-queue §10 and the drafts of
 * §10.4, against the in-memory QueueStore through the real controller
 * logic where it needs no browser, and as pure functions otherwise.
 */
import { describe, expect, it } from "vitest";

import type { CommitmentCaptureContextResponse } from "@leonaid/api-client";
import {
  acceptPrice,
  asDraft,
  asVisit,
  bookAnyway,
  conflictText,
  followUpDueAt,
  nextSendable,
  preflightConflict,
  resolutionsFor,
  withWindow,
  type ActivityEntry,
  type CommitmentEntry,
  type QueueEntry,
} from "@leonaid/features/offline";

const NOW = new Date("2026-11-07T12:00:00Z");

function common(overrides: Partial<QueueEntry> = {}) {
  return {
    actionId: "action",
    assignmentId: "assignment",
    attempts: 1,
    base: {},
    capturedAt: NOW.toISOString(),
    dependsOn: null,
    entryId: "entry",
    idempotencyKey: "pwa-q:entry",
    lastError: null,
    nextAttemptAt: null,
    party: {
      displayName: "Bäckerei Kern",
      id: "party",
      kind: "company" as const,
    },
    previousKeys: [],
    sequence: 1,
    settledAt: null,
    state: "conflict" as const,
    ...overrides,
  };
}

function order(code: string, details: Record<string, unknown> = {}) {
  return {
    ...common({
      base: { unitPriceMinor: 3600, windowId: "w1", windowFullyBooked: false },
      lastError: { code, details, message: code, status: 409 },
    }),
    kind: "commitment",
    request: {
      buyer: {
        displayName: "Bäckerei Kern",
        partyKind: "company",
        twentyId: "party",
      },
      deliveryWindowId: "w1",
      lines: [
        {
          offeringId: "krapfen",
          quantity: 2,
          quotedUnitPriceMinor: 3600,
          unit: "box",
        },
      ],
      readyForReview: true,
      source: "acquisition",
    },
  } as CommitmentEntry;
}

function contact(code: string, note: string | null = "Chefin im Urlaub") {
  return {
    ...common({ lastError: { code, message: code, status: 409 } }),
    kind: "activity",
    request: {
      channel: "email",
      dueOn: "2026-11-12",
      nextAction: "Angebot schicken",
      note,
      outcome: "follow_up",
      partyId: "party",
      partyKind: "company",
      revision: 7,
    },
  } as ActivityEntry;
}

const window = (id: string, fullyBooked: boolean, retired = false) => ({
  deliveryOn: "2026-11-12",
  endsAt: "2026-11-12T09:00:00Z",
  fullyBooked,
  id,
  retired,
  startsAt: "2026-11-12T07:00:00Z",
});

describe("choices (§10)", () => {
  it("offers what the table of §10 lists", () => {
    expect(resolutionsFor(contact("follow_up_not_applied"))).toEqual([
      "keep-follow-up",
      "discard-follow-up",
    ]);
    expect(resolutionsFor(contact("contact_suppressed"))).toEqual([
      "as-visit",
      "discard",
    ]);
    expect(resolutionsFor(contact("sponsor_not_assigned"))).toEqual([
      "copy-note",
      "discard",
    ]);
    expect(resolutionsFor(order("delivery_window_full"))).toEqual([
      "book-anyway",
      "other-window",
      "as-draft",
      "discard",
    ]);
    expect(resolutionsFor(order("delivery_window_unavailable"))).toEqual([
      "other-window",
      "as-draft",
      "discard",
    ]);
    expect(resolutionsFor(order("commitment_price_changed"))).toEqual([
      "accept-price",
      "discard",
    ]);
    expect(resolutionsFor(order("delivery_required"))).toEqual([
      "complete-delivery",
      "as-draft",
      "discard",
    ]);
    expect(resolutionsFor(contact("status_not_applied"))).toEqual([
      "keep-status",
      "discard-status",
    ]);
    expect(resolutionsFor(order("offering_not_available"))).toEqual([
      "discard",
    ]);
  });

  it("changes the body as each choice says", () => {
    expect(asVisit(contact("contact_suppressed")).request.channel).toBe(
      "in_person",
    );
    const full = order("delivery_window_full");
    expect(bookAnyway(full).request.allowFullWindow).toBe(true);
    expect(asDraft(full).request).toMatchObject({
      allowFullWindow: false,
      readyForReview: false,
    });
    expect(withWindow(full, window("w2", false)).request).toMatchObject({
      allowFullWindow: false,
      deliveryWindowId: "w2",
    });
    const priced = acceptPrice(
      order("commitment_price_changed", {
        currency: "EUR",
        lines: [{ offeringId: "krapfen", unitPriceMinor: 3800 }],
        totalMinor: 7600,
      }),
    );
    expect(priced?.request.lines[0]?.quotedUnitPriceMinor).toBe(3800);
    expect(priced?.base.unitPriceMinor).toBe(3800);
    // Without Core's price for every line there is nothing to accept.
    expect(acceptPrice(order("commitment_price_changed"))).toBeNull();
  });

  it("explains the price change in euros (§10.2)", () => {
    expect(
      conflictText(
        order("commitment_price_changed", {
          currency: "EUR",
          lines: [
            {
              offeringId: "krapfen",
              quotedUnitPriceMinor: 3600,
              unitPriceMinor: 3800,
            },
          ],
          totalMinor: 7600,
        }),
        "Krapfentaxi 2026",
      ),
    ).toBe(
      "Der Preis ist jetzt 38,00 € statt 36,00 €. Die Bestellung kostet 76,00 €.",
    );
    expect(
      conflictText(order("commitment_action_closed"), "Krapfentaxi 2026"),
    ).toBe("Für Krapfentaxi 2026 nimmt der Club keine Bestellungen mehr an.");
  });
});

describe("before sending (§10.3)", () => {
  const context = (fullyBooked: boolean, retired = false) =>
    ({
      actionId: "action",
      actionName: "Krapfentaxi 2026",
      deliveryConfiguration: {
        actionId: "action",
        enabled: true,
        revision: 1,
        timezone: "Europe/Berlin",
        windows: [window("w1", fullyBooked, retired)],
      },
      offerings: [],
    }) as CommitmentCaptureContextResponse;

  it("asks before sending into a window the device copy shows full", () => {
    const queued = { ...order(""), state: "queued" as const, lastError: null };
    expect(preflightConflict(queued, context(false))).toBeNull();
    expect(preflightConflict(queued, context(true))).toBe(
      "delivery_window_full",
    );
    expect(preflightConflict(queued, context(false, true))).toBe(
      "delivery_window_unavailable",
    );
    // "Trotzdem eintragen" was already chosen, or it is a draft.
    expect(preflightConflict(bookAnyway(queued), context(true))).toBeNull();
    expect(preflightConflict(asDraft(queued), context(true))).toBeNull();
  });
});

describe("sponsor drafts (§10.4)", () => {
  it("never sends a draft or what waits for it", () => {
    const draft = {
      ...common({ state: "queued", entryId: "draft" }),
      kind: "sponsor-draft",
      mode: "company",
      request: { companyName: "Fa. Muster" },
    } as QueueEntry;
    const waiting = {
      ...contact(""),
      dependsOn: "draft",
      entryId: "after",
      party: { displayName: "Fa. Muster", id: "draft:draft", kind: "company" },
      sequence: 2,
      state: "queued",
    } as QueueEntry;
    expect(nextSendable([draft, waiting], NOW)).toBeNull();
  });
});

describe("my follow-up (§11.4)", () => {
  it("is due at 09:00 on the chosen day, with the device offset", () => {
    const due = followUpDueAt("2026-11-12");
    expect(due).toMatch(/^2026-11-12T09:00:00[+-]\d{2}:\d{2}$/);
    // The instant is 09:00 on that day in the device's own zone.
    const local = new Date(Date.parse(due));
    expect([
      local.getFullYear(),
      local.getMonth() + 1,
      local.getDate(),
    ]).toEqual([2026, 11, 12]);
    expect([local.getHours(), local.getMinutes()]).toEqual([9, 0]);
  });
});
