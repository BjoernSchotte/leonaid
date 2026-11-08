/*
 * The capture queue of specs/pwa-offline-queue §9 and §15 (unit level):
 * ordering per sponsor, classification of Core's answers, backoff,
 * retention and the base revision rule, against the in-memory QueueStore.
 * The `send` step answers like Core would; IndexedDB, Web Locks and the
 * real Core run in the browser specs.
 */
import { describe, expect, it } from "vitest";

import {
  ApiError,
  type RecordAcquisitionActivityResponse,
} from "@leonaid/api-client";
import {
  MemoryQueueStore,
  backoffDelay,
  capturedAtNow,
  classifyFailure,
  conflictText,
  drainQueue,
  nextSendable,
  retention,
  type QueueEntry,
  type SendResult,
} from "@leonaid/features/offline";

import { queueIndicator } from "./queue-indicator";

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
