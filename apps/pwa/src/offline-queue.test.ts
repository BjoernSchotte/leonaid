// @vitest-environment jsdom
/*
 * The capture queue of specs/pwa-offline-queue §9 and §15 (unit level):
 * ordering per sponsor, classification of Core's answers, backoff,
 * retention and the base revision rule, against the in-memory QueueStore.
 * The `send` step answers like Core would; IndexedDB, Web Locks and the
 * real Core run in the browser specs.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  type DeliveryDropResponse,
  type DeliveryTourResponse,
  type MyTourResponse,
  type RecordAcquisitionActivityResponse,
} from "@leonaid/api-client";
import {
  MemoryQueueStore,
  QueueController,
  entryTitle,
  withQueuedWrites,
  backoffDelay,
  capturedAtNow,
  classifyFailure,
  conflictText,
  drainQueue,
  nextSendable,
  resolutionsFor,
  retention,
  type QueueEntry,
  type SendResult,
} from "@leonaid/features/offline";

import { queueIndicator, queueOfflineText } from "./queue-indicator";

const NOW = new Date("2026-11-07T12:00:00Z");
const DAY = 86_400_000;
const ACTION = "20000000-0000-4000-8000-000000000001";

function activity(
  sequence: number,
  partyId: string,
  overrides: Partial<QueueEntry> = {},
): QueueEntry {
  const entryId = `00000000-0000-4000-8000-${String(sequence).padStart(12, "0")}`;
  return {
    actionId: ACTION,
    assignmentId: `assignment-${partyId}`,
    attempts: 0,
    base: { assignmentRevision: 7 },
    capturedAt: NOW.toISOString(),
    dependsOn: null,
    entryId,
    idempotencyKey: `pwa-q:${entryId}`,
    kind: "activity",
    lastError: null,
    nextAttemptAt: null,
    party: { displayName: `Sponsor ${partyId}`, id: partyId, kind: "company" },
    previousKeys: [],
    request: {
      channel: "phone",
      dueOn: "2026-11-12",
      nextAction: "Nachfassen",
      note: null,
      outcome: "follow_up",
      partyId,
      partyKind: "company",
      revision: 7,
    },
    sequence,
    settledAt: null,
    state: "queued",
    ...overrides,
  } as QueueEntry;
}

function apiError(
  status: number,
  code: string,
  retryAfter: number | null = null,
) {
  return new ApiError(
    status,
    { code, message: code, requestId: "r" },
    retryAfter,
  );
}

function accepted(
  entry: QueueEntry,
  revision: number,
  assignmentUpdated = true,
): SendResult {
  const request = entry.kind === "activity" ? entry.request : null;
  const response: RecordAcquisitionActivityResponse = {
    activity: {
      actionId: entry.actionId,
      actorDisplayName: "Anna",
      actorUserId: "u",
      assignmentId: entry.assignmentId,
      assignmentRevision: revision,
      channel: request?.channel ?? "phone",
      dueAt: null,
      id: `activity-${entry.sequence}`,
      nextAction: null,
      note: null,
      occurredAt: entry.capturedAt,
      outcome: request?.outcome ?? "reached",
      partyDisplayName: entry.party.displayName,
      partyId: entry.party.id,
      partyKind: entry.party.kind,
    },
    assignment: {
      acquirerDisplayName: "Anna",
      acquirerUserId: "u",
      actionId: entry.actionId,
      createdAt: NOW.toISOString(),
      dueAt: "2026-11-12T08:00:00Z",
      id: entry.assignmentId,
      // Someone else's later change: never the base of the next entry.
      nextAction: "Angebot schicken",
      partyId: entry.party.id,
      partyKind: entry.party.kind,
      priority: 1,
      revision: revision + 5,
      status: "contacted",
      updatedAt: NOW.toISOString(),
    },
    assignmentUpdated,
    replayed: false,
  };
  return { kind: "activity", response };
}

describe("ordering (§9.2)", () => {
  it("sends per sponsor in capture order; a decision holds only its sponsor", () => {
    const entries = [
      activity(1, "a", { state: "conflict" }),
      activity(2, "a"),
      activity(3, "b"),
    ];
    expect(nextSendable(entries, NOW)?.sequence).toBe(3);
    expect(
      nextSendable([activity(2, "a"), activity(1, "a")], NOW)?.sequence,
    ).toBe(1);
  });

  it("waits for the backoff and never sends expired or blocked entries", () => {
    const later = new Date(NOW.getTime() + 60_000).toISOString();
    const entries = [
      activity(1, "a", { nextAttemptAt: later }),
      activity(2, "a"),
      activity(3, "b", { state: "expired" }),
      activity(4, "c", { state: "blocked" }),
      activity(5, "b"),
    ];
    // Sponsor a waits for entry 1; expired/blocked hold nothing back.
    expect(nextSendable(entries, NOW)?.sequence).toBe(5);
    expect(nextSendable(entries.slice(0, 2), NOW)).toBeNull();
  });

  it("does not send an entry that waits for a sponsor draft", () => {
    expect(
      nextSendable([activity(1, "a", { dependsOn: "draft" })], NOW),
    ).toBeNull();
  });
});

describe("classification (§9.4)", () => {
  it("maps Core's answers to the queue's next step", () => {
    expect(classifyFailure(new TypeError("Failed to fetch")).type).toBe(
      "transient",
    );
    for (const status of [502, 503, 504]) {
      expect(classifyFailure(apiError(status, "x")).type).toBe("transient");
    }
    expect(classifyFailure(apiError(409, "idempotency_incomplete")).type).toBe(
      "transient",
    );
    expect(classifyFailure(apiError(429, "rate_limited", 30))).toEqual({
      retryAfterMs: 30_000,
      type: "transient",
    });
    expect(classifyFailure(apiError(401, "session_required")).type).toBe(
      "paused",
    );
    // 503 maintenance with Retry-After waits at least that long (§9.4).
    expect(classifyFailure(apiError(503, "maintenance_mode", 60))).toEqual({
      retryAfterMs: 60_000,
      type: "transient",
    });
    const missing = classifyFailure(apiError(404, "resource_not_found"));
    expect(missing.type === "conflict" && missing.error.code).toBe(
      "sponsor_not_assigned",
    );
    expect(classifyFailure(apiError(409, "idempotency_conflict")).type).toBe(
      "failed",
    );
    for (const code of [
      "delivery_window_full",
      "commitment_price_changed",
      "contact_suppressed",
      "captured_at_out_of_range",
    ]) {
      const status = code === "captured_at_out_of_range" ? 422 : 409;
      expect(classifyFailure(apiError(status, code)).type).toBe("conflict");
    }
    expect(classifyFailure(apiError(500, "internal")).type).toBe("unknown");
  });
});

describe("backoff (§9.4)", () => {
  it("doubles from 2 s, caps at 5 minutes, jitters ±20 %", () => {
    const middle = () => 0.5;
    expect([1, 2, 3, 4].map((n) => backoffDelay(n, middle))).toEqual([
      2_000, 4_000, 8_000, 16_000,
    ]);
    expect(backoffDelay(20, middle)).toBe(300_000);
    expect(backoffDelay(1, () => 0)).toBe(1_600);
    expect(backoffDelay(1, () => 0.999_999)).toBe(2_400);
  });
});

describe("retention (D5)", () => {
  it("expires after 14 days and deletes 2 days after settling", () => {
    const at = (days: number) =>
      new Date(NOW.getTime() - days * DAY).toISOString();
    expect(retention(activity(1, "a", { capturedAt: at(13) }), NOW)).toBe(
      "keep",
    );
    expect(retention(activity(1, "a", { capturedAt: at(15) }), NOW)).toBe(
      "expire",
    );
    expect(
      retention(activity(1, "a", { state: "expired", settledAt: at(1) }), NOW),
    ).toBe("keep");
    // "Nicht mehr möglich" waits for the acquirer; nothing is deleted unseen.
    expect(
      retention(activity(1, "a", { state: "blocked", settledAt: at(30) }), NOW),
    ).toBe("keep");
    // An entry that may be at Core keeps trying 2 more days (replay).
    expect(
      retention(activity(1, "a", { capturedAt: at(15), everSent: true }), NOW),
    ).toBe("keep");
    expect(
      retention(activity(1, "a", { capturedAt: at(17), everSent: true }), NOW),
    ).toBe("expire");
  });
});

describe("drain", () => {
  it("sends once per entry with its key and moves the base only on assignmentUpdated", async () => {
    const store = new MemoryQueueStore();
    await store.put(activity(1, "a"));
    await store.put(activity(2, "a"));
    const sent: { key: string; revision: number }[] = [];
    const report = await drainQueue({
      now: () => NOW,
      send: async (entry) => {
        if (entry.kind !== "activity") throw new Error("unexpected");
        sent.push({
          key: entry.idempotencyKey,
          revision: entry.request.revision,
        });
        return accepted(entry, entry.request.revision + 1);
      },
      store,
    });
    expect(report.accepted).toHaveLength(2);
    // The second entry is based on the revision the first one produced
    // (8), not on the assignment's current revision (13).
    expect(sent).toEqual([
      { key: "pwa-q:00000000-0000-4000-8000-000000000001", revision: 7 },
      { key: "pwa-q:00000000-0000-4000-8000-000000000002", revision: 8 },
    ]);
    expect(await store.list()).toEqual([]);
  });

  it("keeps a contact whose follow-up was not applied as a decision (D1)", async () => {
    const store = new MemoryQueueStore();
    await store.put(activity(1, "a"));
    await store.put(activity(2, "a"));
    const report = await drainQueue({
      now: () => NOW,
      send: async (entry) => accepted(entry, 7, false),
      store,
    });
    expect(report.accepted).toHaveLength(1);
    const [first, second] = await store.list();
    expect(first).toMatchObject({
      conflictAssignment: { nextAction: "Angebot schicken", revision: 12 },
      lastError: { code: "follow_up_not_applied" },
      state: "conflict",
    });
    // The next entry of the sponsor waits and keeps its own base.
    expect(second).toMatchObject({
      state: "queued",
      base: { assignmentRevision: 7 },
    });
  });

  it("backs off on a lost connection and resends the same key later", async () => {
    const store = new MemoryQueueStore();
    await store.put(activity(1, "a"));
    let clock = NOW;
    const keys: string[] = [];
    const run = (fail: boolean) =>
      drainQueue({
        now: () => clock,
        random: () => 0.5,
        send: async (entry) => {
          keys.push(entry.idempotencyKey);
          if (fail) throw new TypeError("Failed to fetch");
          return accepted(entry, 8);
        },
        store,
      });
    await run(true);
    const [waiting] = await store.list();
    expect(waiting).toMatchObject({
      attempts: 1,
      nextAttemptAt: new Date(NOW.getTime() + 2_000).toISOString(),
      state: "queued",
    });
    // Not due yet: nothing is sent.
    await run(false);
    expect(keys).toHaveLength(1);
    clock = new Date(NOW.getTime() + 2_001);
    await run(false);
    expect(keys).toEqual([waiting!.idempotencyKey, waiting!.idempotencyKey]);
    expect(await store.list()).toEqual([]);
  });

  it("pauses on 401 and blocks the whole action on 403", async () => {
    const store = new MemoryQueueStore();
    await store.put(activity(1, "a"));
    const paused = await drainQueue({
      now: () => NOW,
      send: async () => {
        throw apiError(401, "session_required");
      },
      store,
    });
    expect(paused.paused).toBe(true);
    expect((await store.list())[0]?.state).toBe("queued");

    await store.put(activity(2, "b"));
    await drainQueue({
      now: () => NOW,
      send: async () => {
        throw apiError(403, "acquirer_required");
      },
      store,
    });
    expect((await store.list()).map((entry) => entry.state)).toEqual([
      "blocked",
      "blocked",
    ]);
  });

  it("fails an entry after 5 unknown answers and on a key conflict", async () => {
    const store = new MemoryQueueStore();
    await store.put(activity(1, "a", { attempts: 4 }));
    await store.put(activity(2, "b"));
    await drainQueue({
      now: () => NOW,
      send: async (entry) => {
        throw entry.sequence === 1
          ? apiError(500, "internal")
          : apiError(409, "idempotency_conflict");
      },
      store,
    });
    expect((await store.list()).map((entry) => entry.state)).toEqual([
      "failed",
      "failed",
    ]);
  });

  it("expires entries past 14 days before sending", async () => {
    const store = new MemoryQueueStore();
    await store.put(
      activity(1, "a", {
        capturedAt: new Date(NOW.getTime() - 15 * DAY).toISOString(),
      }),
    );
    const sent: number[] = [];
    await drainQueue({
      now: () => NOW,
      send: async (entry) => {
        sent.push(entry.sequence);
        return accepted(entry, 8);
      },
      store,
    });
    expect(sent).toEqual([]);
    expect((await store.list())[0]).toMatchObject({
      settledAt: NOW.toISOString(),
      state: "expired",
    });
  });

  it("resends an entry left in `sending` by a closed app with the same key", async () => {
    const store = new MemoryQueueStore();
    await store.put(activity(1, "a", { state: "sending", attempts: 1 }));
    const keys: string[] = [];
    await drainQueue({
      now: () => NOW,
      send: async (entry) => {
        keys.push(entry.idempotencyKey);
        return accepted(entry, 8);
      },
      store,
    });
    expect(keys).toEqual(["pwa-q:00000000-0000-4000-8000-000000000001"]);
  });
});

describe("captured at", () => {
  it("is the device time with its offset", () => {
    expect(capturedAtNow(NOW)).toMatch(
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2}:\d{2}$/,
    );
    expect(Date.parse(capturedAtNow(NOW))).toBe(NOW.getTime());
  });
});

describe("queue indicator (§12.2)", () => {
  const snapshot = (states: QueueEntry["state"][], sending = false) => ({
    entries: states.map((state, index) => activity(index + 1, "a", { state })),
    evictable: false,
    loaded: true,
    paused: false,
    sending,
    sent: [],
  });

  it("names the most urgent state, in words", () => {
    expect(queueIndicator(snapshot([]))).toMatchObject({ state: "empty" });
    expect(
      queueIndicator(snapshot(["queued", "queued", "queued"])),
    ).toMatchObject({
      count: 3,
      label: "3 Einträge warten auf Versand",
      state: "waiting",
    });
    expect(queueIndicator(snapshot(["queued"]))).toMatchObject({
      label: "1 Eintrag wartet auf Versand",
    });
    expect(queueIndicator(snapshot(["sending"], true))).toMatchObject({
      label: "Einträge werden gesendet",
      state: "sending",
    });
    expect(queueIndicator(snapshot(["queued", "conflict"]))).toMatchObject({
      count: 1,
      label: "1 Eintrag braucht deine Entscheidung",
      state: "decision",
      waiting: 1,
    });
    expect(
      queueIndicator(snapshot(["conflict", "failed", "failed"])),
    ).toMatchObject({
      count: 2,
      label: "2 Einträge konnten nicht gesendet werden",
      state: "failed",
    });
  });
});

describe("403 per code (§9.4)", () => {
  it("blocks the action only when the acquirer role is gone", () => {
    for (const code of [
      "acquirer_required",
      "commitment_capture_required",
      "commitment_acquisition_required",
    ]) {
      expect(classifyFailure(apiError(403, code)).type).toBe("blocked");
    }
  });

  it("keeps a sponsor-level refusal on that entry", () => {
    const outcome = classifyFailure(
      apiError(403, "commitment_party_not_assigned"),
    );
    expect(outcome.type === "conflict" && outcome.error.code).toBe(
      "sponsor_not_assigned",
    );
    for (const code of [
      "commitment_owner_required",
      "commitment_source_forbidden",
    ]) {
      expect(classifyFailure(apiError(403, code)).type).toBe("conflict");
    }
  });

  it("retries the transport guards and unknown codes, never blocks", () => {
    for (const code of ["csrf_rejected", "cors_origin_rejected"]) {
      expect(classifyFailure(apiError(403, code)).type).toBe("transient");
    }
    expect(classifyFailure(apiError(403, "forbidden")).type).toBe("unknown");
  });

  it("blocks only the action's entries, not another action's", async () => {
    const store = new MemoryQueueStore();
    await store.put(activity(1, "a"));
    await store.put(activity(2, "b", { actionId: "other-action" }));
    await drainQueue({
      now: () => NOW,
      send: async (entry) => {
        if (entry.actionId === ACTION) throw apiError(403, "acquirer_required");
        return accepted(entry, 8);
      },
      store,
    });
    const left = await store.list();
    expect(left.map((entry) => [entry.sequence, entry.state])).toEqual([
      [1, "blocked"],
    ]);
  });

  it("blocks the action's entries whatever the case of its id", async () => {
    const store = new MemoryQueueStore();
    const action = "2000000a-0000-4000-8000-00000000000b";
    await store.put(activity(1, "a", { actionId: action }));
    await store.put(activity(2, "b", { actionId: action.toUpperCase() }));
    let sends = 0;
    await drainQueue({
      now: () => NOW,
      send: async (entry) => {
        sends += 1;
        if (sends === 1) throw apiError(403, "acquirer_required");
        return accepted(entry, 8);
      },
      store,
    });
    expect(sends).toBe(1);
    const left = await store.list();
    expect(left.map((entry) => [entry.sequence, entry.state])).toEqual([
      [1, "blocked"],
      [2, "blocked"],
    ]);
  });

  it("does not hold a sponsor's later entries behind one sponsor-level 403", async () => {
    const store = new MemoryQueueStore();
    await store.put({
      ...activity(1, "a"),
      kind: "commitment",
    } as QueueEntry);
    await store.put(activity(2, "b"));
    const sent: number[] = [];
    await drainQueue({
      now: () => NOW,
      send: async (entry) => {
        sent.push(entry.sequence);
        if (entry.sequence === 1) {
          throw apiError(403, "commitment_party_not_assigned");
        }
        return accepted(entry, 8);
      },
      store,
    });
    expect(sent).toEqual([1, 2]);
    expect((await store.list()).map((entry) => entry.state)).toEqual([
      "conflict",
    ]);
  });
});

describe("D1 without a follow-up (§11.4)", () => {
  it("reports a status Core did not apply instead of dropping it", async () => {
    const store = new MemoryQueueStore();
    await store.put(
      activity(1, "a", {
        request: {
          channel: "phone",
          dueOn: null,
          nextAction: null,
          note: null,
          outcome: "declined",
          partyId: "a",
          partyKind: "company",
          revision: 7,
        },
      } as Partial<QueueEntry>),
    );
    await drainQueue({
      now: () => NOW,
      send: async (entry) => accepted(entry, 7, false),
      store,
    });
    expect((await store.list())[0]).toMatchObject({
      lastError: { code: "status_not_applied" },
      state: "conflict",
    });
  });

  it("deletes the entry when nothing was lost", async () => {
    const store = new MemoryQueueStore();
    await store.put(
      activity(1, "a", {
        request: {
          channel: "phone",
          dueOn: null,
          nextAction: null,
          note: null,
          outcome: "reached",
          partyId: "a",
          partyKind: "company",
          revision: 7,
        },
      } as Partial<QueueEntry>),
    );
    // The assignment is "contacted" already (accepted() answers so).
    await drainQueue({
      now: () => NOW,
      send: async (entry) => accepted(entry, 7, false),
      store,
    });
    expect(await store.list()).toEqual([]);
  });
});

describe("pre-send check (§10.3)", () => {
  it("never turns an entry that may be at Core into a decision", async () => {
    const store = new MemoryQueueStore();
    await store.put(activity(1, "a", { attempts: 1, everSent: true }));
    const keys: string[] = [];
    await drainQueue({
      now: () => NOW,
      preflight: async () => "delivery_window_full",
      send: async (entry) => {
        keys.push(entry.idempotencyKey);
        return accepted(entry, 8);
      },
      store,
    });
    expect(keys).toEqual(["pwa-q:00000000-0000-4000-8000-000000000001"]);
    expect(await store.list()).toEqual([]);
  });

  it("asks before the first send", async () => {
    const store = new MemoryQueueStore();
    await store.put(activity(1, "a"));
    const keys: string[] = [];
    await drainQueue({
      now: () => NOW,
      preflight: async () => "delivery_window_full",
      send: async (entry) => {
        keys.push(entry.idempotencyKey);
        return accepted(entry, 8);
      },
      store,
    });
    expect(keys).toEqual([]);
    expect((await store.list())[0]).toMatchObject({
      lastError: { code: "delivery_window_full" },
      state: "conflict",
    });
  });
});

describe("reasons in Du (§10)", () => {
  it("explains a price change from Core's details (§11.3 shape)", () => {
    const entry = {
      ...activity(1, "a"),
      kind: "commitment",
      lastError: {
        code: "commitment_price_changed",
        details: {
          currency: "EUR",
          lines: [
            {
              lineTotalMinor: 7600,
              offeringId: "krapfen",
              quotedUnitPriceMinor: 3600,
              unitPriceMinor: 3800,
            },
          ],
          totalMinor: 7600,
        },
        message: "",
        status: 409,
      },
      state: "conflict",
    } as QueueEntry;
    expect(conflictText(entry, "Krapfentaxi 2026")).toBe(
      "Der Preis ist jetzt 38,00\u00a0€ statt 36,00\u00a0€. Die Bestellung kostet 76,00\u00a0€.",
    );
  });

  it("names a status Core kept (D1 without follow-up)", () => {
    const entry = activity(1, "a", {
      lastError: { code: "status_not_applied", message: "", status: 201 },
      request: {
        channel: "phone",
        dueOn: null,
        nextAction: null,
        note: null,
        outcome: "declined",
        partyId: "a",
        partyKind: "company",
        revision: 7,
      },
      state: "conflict",
    } as Partial<QueueEntry>);
    expect(conflictText(entry, "")).toContain(
      "Der Status „Abgesagt“ wurde nicht übernommen",
    );
  });
});

/* ---------- "Meine Tour" offline (krapfentaxi-touren §9) ---------- */

describe("driver queue kinds (delivery-state, tour-order)", () => {
  const DRIVER = "10000000-0000-4000-8000-0000000000d1";
  const TODAY = "2026-11-07";
  const stops: (() => void)[] = [];
  afterEach(() => {
    for (const stop of stops.splice(0)) stop();
    vi.restoreAllMocks();
  });

  function tourDrop(
    commitmentId: string,
    extra: Partial<DeliveryDropResponse> = {},
  ): DeliveryDropResponse {
    return {
      address: null,
      buyerName: `Kunde ${commitmentId}`,
      commitmentId,
      contact: null,
      driverName: null,
      driverUserId: DRIVER,
      missedAtClosure: false,
      orderStatus: "review_ready",
      quantities: [{ quantity: 1, unit: "box" }],
      revision: 3,
      state: "open",
      stateChangedAt: null,
      stateChangedByName: null,
      totalBoxes: 1,
      windowId: "w1",
      ...extra,
    };
  }

  /** One window with the stops in this order, revision `revision`. */
  function tour(ids: readonly string[], revision = "r1"): DeliveryTourResponse {
    return {
      day: TODAY,
      driverName: "Dora",
      driverOrderedAt: null,
      driverUserId: DRIVER,
      revision,
      windows: [
        {
          closed: false,
          endsAt: `${TODAY}T20:00:00Z`,
          startsAt: `${TODAY}T08:00:00Z`,
          stops: ids.map((id, index) => ({
            baseRank: index + 1,
            driverRank: null,
            drop: tourDrop(id),
            effectiveRank: index + 1,
            lat: null,
            lon: null,
            newForDriver: false,
          })),
          windowId: "w1",
        },
      ],
    };
  }

  function myTour(value: DeliveryTourResponse): MyTourResponse {
    return {
      actionId: ACTION,
      actionName: "Krapfentaxi",
      days: [TODAY],
      map: { attribution: "OSM", tileUrl: "https://tile/{z}/{x}/{y}.png" },
      startPoint: null,
      timezone: "Europe/Berlin",
      tour: value,
    };
  }

  const isTour = (entry: QueueEntry) =>
    entry.kind === "delivery-state" || entry.kind === "tour-order";

  const shownOrder = (response: MyTourResponse) =>
    response
      .tour!.windows[0]!.stops.toSorted(
        (a, b) => a.effectiveRank - b.effectiveRank,
      )
      .map((stop) => stop.drop.commitmentId);

  /** A controller in a browser that starts offline. */
  function offlineQueue(send: (entry: QueueEntry) => Promise<SendResult>) {
    const online = vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    const store = new MemoryQueueStore();
    const queue = new QueueController({ send, store, userId: DRIVER });
    stops.push(queue.start());
    return {
      queue,
      reconnect: async () => {
        online.mockReturnValue(true);
        await queue.sendNow();
      },
      store,
    };
  }

  const mark = (
    queue: QueueController,
    commitmentId: string,
    fromState: "open" | "delivered" | "missed",
    target: "open" | "delivered" | "missed",
  ) =>
    queue.queueDeliveryState({
      actionId: ACTION,
      commitmentId,
      displayName: `Kunde ${commitmentId}`,
      expectedRevision: 3,
      fromState,
      target,
    });

  const move = (
    queue: QueueController,
    fromOrder: readonly string[],
    commitmentIds: readonly string[],
  ) =>
    queue.queueTourOrder({
      actionId: ACTION,
      commitmentIds,
      day: TODAY,
      displayName: "Sa 07.11.",
      expectedRevision: "r1",
      fromOrder,
    });

  it("delivered offline then undone offline leaves no entry", async () => {
    const send = vi.fn(async (): Promise<SendResult> => {
      throw new Error("nothing is sent offline");
    });
    const { queue, store } = offlineQueue(send);
    expect(await mark(queue, "c1", "open", "delivered")).toBe("queued");
    const [entry] = await store.list();
    expect(entry?.kind).toBe("delivery-state");
    expect(entryTitle(entry!)).toBe("Zustellung Kunde c1: zugestellt");
    // The page shows it at once on top of the device copy.
    const shown = withQueuedWrites(myTour(tour(["c1", "c2"])), [entry!]);
    expect(shown.tour!.windows[0]!.stops[0]!.drop.state).toBe("delivered");
    // "Rückgängig": the stop shows delivered, the undo goes back to open.
    expect(await mark(queue, "c1", "delivered", "open")).toBe("cleared");
    expect(await store.list()).toEqual([]);
    // A second tap on the same state changes nothing.
    await mark(queue, "c1", "open", "delivered");
    expect(await mark(queue, "c1", "delivered", "delivered")).toBe("unchanged");
    expect(await mark(queue, "c1", "delivered", "open")).toBe("cleared");
    // Delivered, then "Nicht da" instead: one entry with the last target.
    await mark(queue, "c2", "open", "delivered");
    await mark(queue, "c2", "delivered", "missed");
    const entries = await store.list();
    expect(entries).toHaveLength(1);
    expect(
      entries[0]!.kind === "delivery-state" && entries[0]!.request,
    ).toEqual({ delivered: false, expectedRevision: 3, missed: true });
    expect(send).not.toHaveBeenCalled();
  });

  it("two tour-order entries collapse to the last", async () => {
    const { queue, store } = offlineQueue(async () => {
      throw new Error("nothing is sent offline");
    });
    await move(queue, ["c1", "c2", "c3"], ["c2", "c1", "c3"]);
    await move(queue, ["c2", "c1", "c3"], ["c3", "c2", "c1"]);
    const entries = await store.list();
    expect(entries).toHaveLength(1);
    const [entry] = entries;
    expect(entry?.kind === "tour-order" && entry.request).toEqual({
      commitmentIds: ["c3", "c2", "c1"],
      day: TODAY,
      expectedRevision: "r1",
    });
    expect(entryTitle(entry!)).toBe("Tour-Reihenfolge Sa 07.11.");
    expect(
      shownOrder(withQueuedWrites(myTour(tour(["c1", "c2", "c3"])), entries)),
    ).toEqual(["c3", "c2", "c1"]);
    // Moved back to where it started: nothing left to send.
    expect(await move(queue, ["c3", "c2", "c1"], ["c1", "c2", "c3"])).toBe(
      "cleared",
    );
    expect(await store.list()).toEqual([]);
  });

  it("tour-order conflict after an appended stop shows Vom Planer geändert and keeps the server order", async () => {
    const { queue, reconnect, store } = offlineQueue(async () => {
      // The planner appended c4: the driver's ids no longer match the tour.
      throw apiError(409, "tour_order_stale");
    });
    await move(queue, ["c1", "c2", "c3"], ["c3", "c1", "c2"]);
    await reconnect();
    const [entry] = await store.list();
    expect(entry?.state).toBe("conflict");
    expect(conflictText(entry!, "Krapfentaxi")).toMatch(
      /^Vom Planer geändert\. .*Es gilt die Reihenfolge der Planung\.$/,
    );
    // Refused entries no longer show: the page shows Core's order.
    const server = myTour(tour(["c1", "c2", "c3", "c4"], "r2"));
    expect(shownOrder(withQueuedWrites(server, [entry!]))).toEqual([
      "c1",
      "c2",
      "c3",
      "c4",
    ]);
    // A revision conflict of a mark reads the same.
    expect(
      conflictText(
        {
          ...entry!,
          kind: "delivery-state",
          commitmentId: "c1",
          fromState: "open",
          lastError: {
            code: "delivery_state_conflict",
            message: "",
            status: 409,
          },
          request: { delivered: true, expectedRevision: 3, missed: false },
        } as QueueEntry,
        "",
      ),
    ).toMatch(/^Vom Planer geändert\./);
    expect(classifyFailure(apiError(409, "tour_revision_conflict")).type).toBe(
      "conflict",
    );
  });

  it("window closed while offline shows Fenster geschlossen", async () => {
    const { queue, reconnect, store } = offlineQueue(async () => {
      throw apiError(409, "delivery_window_closed");
    });
    await mark(queue, "c1", "open", "missed");
    await reconnect();
    const [entry] = await store.list();
    expect(entry?.state).toBe("conflict");
    expect(conflictText(entry!, "")).toMatch(/^Fenster geschlossen\. /);
    // The stop shows Core's state again, not the refused mark.
    expect(
      withQueuedWrites(myTour(tour(["c1"])), [entry!]).tour!.windows[0]!
        .stops[0]!.drop.state,
    ).toBe("open");
    // Other refusals of a driver's entry.
    const reassigned = classifyFailure(apiError(403, "delivery_not_assigned"));
    expect(reassigned.type === "conflict" && reassigned.error.code).toBe(
      "delivery_not_assigned",
    );
    expect(
      classifyFailure(apiError(403, "delivery_board_forbidden")).type,
    ).toBe("blocked");
    // Only "Verwerfen": no acquirer choice for a driver's entry, even for
    // a code the captures share.
    expect(resolutionsFor(entry!)).toEqual(["discard"]);
    expect(
      resolutionsFor({
        ...entry!,
        lastError: { code: "delivery_window_full", message: "", status: 409 },
      }),
    ).toEqual(["discard"]);
  });

  /** A queued mark of stop `commitmentId`, number `sequence`. */
  function stopEntry(sequence: number, commitmentId: string): QueueEntry {
    return {
      ...activity(sequence, `stop:${commitmentId}`),
      commitmentId,
      fromState: "open",
      kind: "delivery-state",
      request: { delivered: true, expectedRevision: 3, missed: false },
    } as QueueEntry;
  }

  it("a refused role blocks only its own entries", async () => {
    for (const lost of ["driver", "acquirer"] as const) {
      const store = new MemoryQueueStore();
      await store.put(
        lost === "driver" ? stopEntry(1, "c1") : activity(1, "a"),
      );
      await store.put(
        lost === "driver" ? activity(2, "a") : stopEntry(2, "c1"),
      );
      const sent: string[] = [];
      await drainQueue({
        now: () => NOW,
        send: async (entry) => {
          if (isTour(entry) === (lost === "driver")) {
            throw apiError(
              403,
              lost === "driver"
                ? "delivery_board_forbidden"
                : "acquirer_required",
            );
          }
          sent.push(entry.kind);
          return isTour(entry)
            ? { kind: "delivery-state", response: tourDrop("c1") }
            : accepted(entry, 8);
        },
        store,
      });
      const left = await store.list();
      expect(left.map((entry) => [entry.kind, entry.state])).toEqual([
        [lost === "driver" ? "delivery-state" : "activity", "blocked"],
      ]);
      expect(sent).toEqual([lost === "driver" ? "activity" : "delivery-state"]);
    }
  });

  it("entries replay in sequence after reconnect", async () => {
    const sent: string[] = [];
    let revision = 3;
    let first = true;
    const { queue, reconnect, store } = offlineQueue(async (entry) => {
      if (entry.kind === "delivery-state") {
        sent.push(`${entry.commitmentId}@${entry.request.expectedRevision}`);
        if (first && entry.commitmentId === "c1") {
          // The answer of the first mark is lost: sent, but not confirmed.
          first = false;
          throw new TypeError("Failed to fetch");
        }
        revision += 1;
        return {
          kind: "delivery-state",
          response: tourDrop(entry.commitmentId, { revision }),
        };
      }
      if (entry.kind === "tour-order") {
        sent.push(`order@${entry.request.expectedRevision}`);
        return {
          kind: "tour-order",
          response: tour(entry.request.commitmentIds, "r2"),
        };
      }
      throw new Error(`unexpected ${entry.kind}`);
    });
    await mark(queue, "c1", "open", "delivered");
    await move(queue, ["c1", "c2", "c3"], ["c1", "c3", "c2"]);
    await mark(queue, "c3", "open", "missed");
    await reconnect();
    // The lost answer: a retry with backoff, and the drain stops there
    // (no network for the others either). Nothing is lost or reordered.
    let entries = await store.list();
    expect(entries.map((entry) => entry.kind)).toEqual([
      "delivery-state",
      "tour-order",
      "delivery-state",
    ]);
    expect(entries[0]!.everSent).toBe(true);
    // The driver undoes c1 before the retry: the mark may be at Core
    // already, so the undo is a new entry after it, not a deletion. Its
    // write starts a run: the other lines go on, c1's line waits for the
    // backoff and keeps its order.
    expect(await mark(queue, "c1", "delivered", "open")).toBe("queued");
    await vi.waitFor(() => expect(sent).toHaveLength(3));
    expect(sent).toEqual(["c1@3", "order@r1", "c3@3"]);
    await queue.sendNow();
    expect(sent).toEqual([
      "c1@3",
      "order@r1",
      "c3@3",
      // The replay of the mark Core may have, then the undo with the
      // revision Core returned for it (5).
      "c1@3",
      "c1@5",
    ]);
    entries = await store.list();
    expect(entries).toEqual([]);
    expect(queue.snapshot.sent.map((entry) => entry.kind)).toEqual([
      "tour-order",
      "delivery-state",
      "delivery-state",
      "delivery-state",
    ]);
  });
});

describe("offline banner text by role (Ruling 22)", () => {
  it("speaks of the tour to a driver, of captures to an acquirer", () => {
    const driver = queueOfflineText({ acquirer: false, driver: true });
    expect(driver).toContain("Zustellungen und deine Reihenfolge");
    expect(driver).not.toMatch(/Kontakte|Wiedervorlagen|Bestellungen/);
    expect(queueOfflineText({ acquirer: true, driver: false })).toContain(
      "Neue Kontakte, Wiedervorlagen und Bestellungen",
    );
    expect(queueOfflineText({ acquirer: true, driver: true })).toContain(
      "Bestellungen und Zustellungen",
    );
    // A driver with tours off: only what still waits goes out.
    const neither = queueOfflineText({ acquirer: false, driver: false });
    expect(neither).toContain("noch wartet");
    expect(neither).not.toMatch(/Kontakte|Bestellungen|Zustellungen/);
  });
});
