// @vitest-environment jsdom
/*
 * The capture queue as pages drive it (specs/pwa-offline-queue §9.1):
 * submit outcomes, and changes during a send in flight (M1 of the #131
 * review). Uses the in-memory QueueStore; `send` answers like Core.
 */
import { afterEach, describe, expect, it } from "vitest";

import {
  ApiError,
  type RecordAcquisitionActivityResponse,
} from "@leonaid/api-client";
import {
  MemoryQueueStore,
  QueueController,
  type QueueDraft,
  type QueueEntry,
  type SendResult,
} from "@leonaid/features/offline";

const USER = "10000000-0000-4000-8000-000000000004";

function draft(partyId = "party"): QueueDraft {
  return {
    actionId: "action",
    assignmentId: "assignment",
    base: { assignmentRevision: 7 },
    kind: "activity",
    party: { displayName: "Bäckerei Kern", id: partyId, kind: "company" },
    request: {
      channel: "phone",
      dueOn: null,
      nextAction: null,
      note: "Chefin im Urlaub",
      outcome: "reached",
      partyId,
      partyKind: "company",
      revision: 7,
    },
  } as QueueDraft;
}

function accepted(entry: QueueEntry): SendResult {
  const response = {
    activity: { assignmentRevision: 8 },
    assignment: { status: "contacted" },
    assignmentUpdated: true,
  } as unknown as RecordAcquisitionActivityResponse;
  void entry;
  return { kind: "activity", response };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, reject, resolve };
}

const stops: (() => void)[] = [];
afterEach(() => {
  for (const stop of stops.splice(0)) stop();
});

function controller(send: (entry: QueueEntry) => Promise<SendResult>) {
  const store = new MemoryQueueStore();
  const queue = new QueueController({ send, store, userId: USER });
  stops.push(queue.start());
  return { queue, store };
}

describe("QueueController", () => {
  it("sends a capture at once online and reports Core's answer", async () => {
    const keys: string[] = [];
    const { queue, store } = controller(async (entry) => {
      keys.push(entry.idempotencyKey);
      return accepted(entry);
    });
    const outcome = await queue.submit(draft());
    expect(outcome.state).toBe("accepted");
    expect(keys).toEqual([`pwa-q:${outcome.entryId}`]);
    expect(await store.list()).toEqual([]);
    expect(queue.snapshot.sent.map((entry) => entry.entryId)).toEqual([
      outcome.entryId,
    ]);
  });

  it("reports a decision with Core's code and keeps the entry", async () => {
    const { queue, store } = controller(async () => {
      throw new ApiError(409, {
        code: "contact_suppressed",
        message: "x",
        requestId: "r",
      });
    });
    const outcome = await queue.submit(draft());
    expect(outcome).toMatchObject({
      error: { code: "contact_suppressed" },
      state: "conflict",
    });
    expect((await store.list()).map((entry) => entry.state)).toEqual([
      "conflict",
    ]);
  });

  it("says why an entry is still waiting after a retryable answer", async () => {
    const { queue } = controller(async () => {
      throw new ApiError(
        503,
        {
          code: "maintenance_mode",
          message: "x",
          requestId: "r",
        },
        60,
      );
    });
    const outcome = await queue.submit(draft());
    expect(outcome).toMatchObject({ reason: "retry", state: "queued" });
    const [entry] = queue.snapshot.entries;
    // Retry-After 60 s is honoured over the 2 s backoff.
    expect(Date.parse(entry!.nextAttemptAt!) - Date.now()).toBeGreaterThan(
      55_000,
    );
  });

  it("shows a send in flight and lets a discard wait for it", async () => {
    const answer = deferred<SendResult>();
    let sends = 0;
    const { queue, store } = controller(async () => {
      sends += 1;
      return answer.promise;
    });
    const submitted = queue.submit(draft());
    await expect
      .poll(() => queue.snapshot.entries.map((entry) => entry.state))
      .toEqual(["sending"]);
    const entryId = queue.snapshot.entries[0]!.entryId;
    const discarded = queue.discard(entryId);
    // The answer is lost (connection reset): the entry must not come back.
    answer.reject(new TypeError("Failed to fetch"));
    await discarded;
    await submitted;
    expect(await store.list()).toEqual([]);
    expect(queue.snapshot.entries).toEqual([]);
    expect(sends).toBe(1);
  });

  it("never resends a discarded entry after a slow accepted answer", async () => {
    const answer = deferred<SendResult>();
    const { queue, store } = controller(async (entry) => {
      void entry;
      return answer.promise;
    });
    const submitted = queue.submit(draft());
    await expect
      .poll(() => queue.snapshot.entries.map((entry) => entry.state))
      .toEqual(["sending"]);
    const entryId = queue.snapshot.entries[0]!.entryId;
    const discarded = queue.discard(entryId);
    answer.resolve(accepted(queue.snapshot.entries[0]!));
    await Promise.all([discarded, submitted]);
    expect(await store.list()).toEqual([]);
  });

  it("'Jetzt senden' and 'Erneut versuchen' do not undo a send in flight", async () => {
    const answer = deferred<SendResult>();
    const { queue, store } = controller(async () => answer.promise);
    const submitted = queue.submit(draft());
    await expect
      .poll(() => queue.snapshot.entries.map((entry) => entry.state))
      .toEqual(["sending"]);
    const entryId = queue.snapshot.entries[0]!.entryId;
    const nudged = Promise.all([queue.sendNow(), queue.retry(entryId)]);
    answer.resolve(accepted(queue.snapshot.entries[0]!));
    await Promise.all([nudged, submitted]);
    expect(await store.list()).toEqual([]);
  });

  it("keeps the same key when a choice keeps the body, a new one otherwise", async () => {
    let fail = true;
    const keys: string[] = [];
    const { queue } = controller(async (entry) => {
      keys.push(entry.idempotencyKey);
      if (fail) {
        throw new ApiError(409, {
          code: "contact_suppressed",
          message: "x",
          requestId: "r",
        });
      }
      return accepted(entry);
    });
    const first = await queue.submit(draft());
    fail = false;
    const again = await queue.resubmit(first.entryId, (entry) => entry, {
      newKey: false,
    });
    expect(again?.state).toBe("accepted");
    expect(keys).toEqual([`pwa-q:${first.entryId}`, `pwa-q:${first.entryId}`]);
  });

  it("resubmits an edited body with a new key, and reports a discarded entry as gone (#131 N1)", async () => {
    let fail = true;
    const sent: { key: string; note: unknown }[] = [];
    const { queue } = controller(async (entry) => {
      sent.push({
        key: entry.idempotencyKey,
        note: (entry.request as { note?: unknown }).note,
      });
      if (fail) {
        throw new ApiError(409, {
          code: "contact_suppressed",
          message: "x",
          requestId: "r",
        });
      }
      return accepted(entry);
    });
    const first = await queue.submit(draft());
    fail = false;
    const edited = await queue.resubmit(
      first.entryId,
      (entry) =>
        ({ ...entry, request: { ...entry.request, note: "edited" } }) as never,
      { newKey: true },
    );
    expect(edited?.state).toBe("accepted");
    expect(sent).toHaveLength(2);
    expect(sent[1]!.note).toBe("edited");
    expect(sent[1]!.key).not.toBe(sent[0]!.key);

    fail = true;
    const second = await queue.submit(draft());
    await queue.discard(second.entryId);
    const gone = await queue.resubmit(second.entryId, (entry) => entry, {
      newKey: true,
    });
    expect(gone).toBeNull();
  });

  it("does not send while offline and sends when the network returns", async () => {
    const keys: string[] = [];
    const { queue, store } = controller(async (entry) => {
      keys.push(entry.idempotencyKey);
      return accepted(entry);
    });
    Object.defineProperty(navigator, "onLine", {
      configurable: true,
      get: () => false,
    });
    const outcome = await queue.submit(draft());
    expect(outcome).toMatchObject({ reason: "offline", state: "queued" });
    expect(keys).toEqual([]);
    Object.defineProperty(navigator, "onLine", {
      configurable: true,
      get: () => true,
    });
    window.dispatchEvent(new Event("online"));
    await expect.poll(async () => (await store.list()).length).toBe(0);
    expect(keys).toEqual([`pwa-q:${outcome.entryId}`]);
  });

  it("never deletes a dependent the discard confirmation did not name (#132 N2)", async () => {
    const { queue, store } = controller(async (entry) => accepted(entry));
    const sponsor = await queue.saveDraft({
      actionId: "action",
      mode: "company",
      request: { companyName: "Neue Bäckerei" } as never,
    });
    const dependent = (note: string) =>
      ({
        ...draft(sponsor.party.id),
        assignmentId: sponsor.assignmentId,
        dependsOn: sponsor.entryId,
        request: { ...draft(sponsor.party.id).request, note },
      }) as QueueDraft;
    const first = await queue.submit(dependent("eins"));
    const shown = (await queue.dependents(sponsor.entryId)).map(
      (entry) => entry.entryId,
    );
    expect(shown).toEqual([first.entryId]);
    // Another tab captures a second contact for the draft meanwhile.
    await queue.submit(dependent("zwei"));
    expect(await queue.discard(sponsor.entryId, shown)).toBe("changed");
    expect(await store.list()).toHaveLength(3);
    const again = (await queue.dependents(sponsor.entryId)).map(
      (entry) => entry.entryId,
    );
    expect(await queue.discard(sponsor.entryId, again)).toBe("discarded");
    expect(await store.list()).toEqual([]);
  });
});
