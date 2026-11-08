// @vitest-environment jsdom
/*
 * The CRM check of a sponsor draft after a lost answer (specs/pwa-offline-
 * queue §10.4, review #132 N1). `resolveSponsorMatch` behaves like Core:
 * idempotent on the command id and the exact body.
 */
import { afterEach, describe, expect, it } from "vitest";

import {
  ApiError,
  type LeonAidApiClient,
  type RecordAcquisitionActivityResponse,
  type ResolveSponsorMatchRequest,
  type SponsorResolutionResponse,
} from "@leonaid/api-client";
import {
  MemoryQueueStore,
  QueueController,
  drainQueue,
  resolveDraftSponsor,
  resumeDraftCheck,
  type QueueDraft,
  type QueueEntry,
  type SendResult,
  type SponsorDraftEntry,
} from "@leonaid/features/offline";

const USER = "10000000-0000-4000-8000-000000000004";
const ACTION = "action";

/** Core's resolve: one sponsor per command, replayed for the same body. */
function fakeCore({ loseFirstAnswer }: { loseFirstAnswer: boolean }) {
  const receipts = new Map<
    string,
    { body: string; result: SponsorResolutionResponse }
  >();
  let created = 0;
  let lose = loseFirstAnswer;
  const client = {
    resolveSponsorMatch: async (
      _actionId: string,
      request: ResolveSponsorMatchRequest,
    ) => {
      const body = JSON.stringify(request);
      const receipt = receipts.get(request.commandId);
      if (receipt) {
        if (receipt.body !== body) {
          throw new ApiError(409, {
            code: "idempotency_conflict",
            message: "x",
            requestId: "r",
          });
        }
        return receipt.result;
      }
      created += 1;
      const result = {
        assignmentCreated: true,
        assignmentId: "assignment-new",
        displayName: "Neue Bäckerei",
        partyKind: "company",
        twentyId: "twenty-new",
      } as unknown as SponsorResolutionResponse;
      receipts.set(request.commandId, { body, result });
      if (lose) {
        lose = false;
        // Committed at Core; the answer never arrives.
        throw new TypeError("Failed to fetch");
      }
      return result;
    },
  } as unknown as LeonAidApiClient;
  return { client, created: () => created };
}

const stops: (() => void)[] = [];
afterEach(() => {
  for (const stop of stops.splice(0)) stop();
});

function controller() {
  const sent: QueueEntry[] = [];
  const store = new MemoryQueueStore();
  const queue = new QueueController({
    send: async (entry): Promise<SendResult> => {
      sent.push(entry);
      return {
        kind: "activity",
        response: {
          activity: { assignmentRevision: 2 },
          assignment: { status: "contacted" },
          assignmentUpdated: true,
        } as unknown as RecordAcquisitionActivityResponse,
      };
    },
    store,
    userId: USER,
  });
  stops.push(queue.start());
  return { queue, sent, store };
}

async function draftWithContact(queue: QueueController) {
  const draft = await queue.saveDraft({
    actionId: ACTION,
    mode: "company",
    request: { companyName: "Neue Bäckerei" } as never,
  });
  await queue.submit({
    actionId: ACTION,
    assignmentId: draft.assignmentId,
    base: { assignmentRevision: 0 },
    dependsOn: draft.entryId,
    kind: "activity",
    party: draft.party,
    request: {
      channel: "phone",
      dueOn: null,
      nextAction: null,
      note: "Erstkontakt",
      outcome: "reached",
      partyId: draft.party.id,
      partyKind: "company",
      revision: 0,
    },
  } as QueueDraft);
  return draft;
}

function request(draft: SponsorDraftEntry): ResolveSponsorMatchRequest {
  return {
    commandId: draft.commandId,
    confirmExistingAssignments: false,
    expectedStatus: "no_match",
    selectedTwentyId: null,
    sponsor: draft.request,
  } as ResolveSponsorMatchRequest;
}

async function stored(
  queue: QueueController,
  draftId: string,
): Promise<SponsorDraftEntry> {
  await queue.reload();
  return queue.snapshot.entries.find(
    (entry) => entry.entryId === draftId,
  ) as SponsorDraftEntry;
}

describe("draft check (§10.4)", () => {
  it("resolve committed, answer lost, check again: the sponsor once, the contact once", async () => {
    const core = fakeCore({ loseFirstAnswer: true });
    const { queue, sent, store } = controller();
    const draft = await draftWithContact(queue);

    await expect(
      resolveDraftSponsor(
        core.client,
        queue,
        ACTION,
        draft.entryId,
        request(draft),
      ),
    ).rejects.toThrow("Failed to fetch");
    // The draft kept the body it sent; the contact still waits.
    const kept = await stored(queue, draft.entryId);
    expect(kept.resolveRequest).toEqual(request(draft));
    expect(sent).toEqual([]);

    // The next check replays that body instead of building a new one.
    const check = await resumeDraftCheck(core.client, queue, ACTION, kept);
    expect(check.state).toBe("resolved");
    expect(core.created()).toBe(1);
    if (check.state !== "resolved") return;
    expect((await stored(queue, draft.entryId)).resolution).toEqual(
      check.resolution,
    );

    await queue.resolveDraft(draft.entryId, {
      assignmentId: check.resolution.assignmentId,
      displayName: check.resolution.displayName,
      partyId: check.resolution.twentyId,
      partyKind: check.resolution.partyKind,
      revision: 3,
    });
    await expect.poll(() => store.list()).toEqual([]);
    expect(sent).toHaveLength(1);
    expect(sent[0]!.assignmentId).toBe("assignment-new");
  });

  it("uses a known answer without asking Core again", async () => {
    const core = fakeCore({ loseFirstAnswer: false });
    const { queue } = controller();
    const draft = await draftWithContact(queue);
    await resolveDraftSponsor(
      core.client,
      queue,
      ACTION,
      draft.entryId,
      request(draft),
    );
    const check = await resumeDraftCheck(
      {
        resolveSponsorMatch: () => Promise.reject(new Error("no call")),
      } as never,
      queue,
      ACTION,
      await stored(queue, draft.entryId),
    );
    expect(check.state).toBe("resolved");
    expect(core.created()).toBe(1);
  });

  it("starts fresh under a new command id after a refusal, waits after no answer", async () => {
    const { queue } = controller();
    const draft = await draftWithContact(queue);
    const refused = {
      resolveSponsorMatch: () =>
        Promise.reject(
          new ApiError(409, {
            code: "sponsor_match_changed",
            message: "x",
            requestId: "r",
          }),
        ),
    } as unknown as LeonAidApiClient;
    await expect(
      resolveDraftSponsor(
        refused,
        queue,
        ACTION,
        draft.entryId,
        request(draft),
      ),
    ).rejects.toBeInstanceOf(ApiError);
    const fresh = await stored(queue, draft.entryId);
    expect(fresh.resolveRequest ?? null).toBeNull();
    expect(fresh.commandId).not.toBe(draft.commandId);
    expect((await resumeDraftCheck(refused, queue, ACTION, fresh)).state).toBe(
      "check",
    );

    const silent = {
      resolveSponsorMatch: () =>
        Promise.reject(new TypeError("Failed to fetch")),
    } as unknown as LeonAidApiClient;
    await expect(
      resolveDraftSponsor(silent, queue, ACTION, draft.entryId, request(fresh)),
    ).rejects.toThrow();
    const waiting = await stored(queue, draft.entryId);
    expect(waiting.commandId).toBe(fresh.commandId);
    expect((await resumeDraftCheck(silent, queue, ACTION, waiting)).state).toBe(
      "unknown",
    );
  });
});

describe("the street of a check leaves the device (E-017)", () => {
  const STREET = "Kontrollweg 9";
  const withStreet = (draft: SponsorDraftEntry) => ({
    ...request(draft),
    sponsor: { ...draft.request, streetLine1: STREET },
  });
  const onDevice = async (store: MemoryQueueStore) =>
    JSON.stringify(await store.list()).includes(STREET);

  it("goes with the draft once it is resolved", async () => {
    const core = fakeCore({ loseFirstAnswer: false });
    const { queue, store } = controller();
    const draft = await draftWithContact(queue);
    const resolution = await resolveDraftSponsor(
      core.client,
      queue,
      ACTION,
      draft.entryId,
      withStreet(draft),
    );
    expect(await onDevice(store)).toBe(true);
    await queue.resolveDraft(draft.entryId, {
      assignmentId: resolution.assignmentId,
      displayName: resolution.displayName,
      partyId: resolution.twentyId,
      partyKind: resolution.partyKind,
      revision: 3,
    });
    await expect.poll(() => store.list()).toEqual([]);
    expect(await onDevice(store)).toBe(false);
  });

  it("goes with the draft when it is discarded", async () => {
    const { queue, store } = controller();
    const draft = await draftWithContact(queue);
    const silent = {
      resolveSponsorMatch: () =>
        Promise.reject(new TypeError("Failed to fetch")),
    } as unknown as LeonAidApiClient;
    await expect(
      resolveDraftSponsor(
        silent,
        queue,
        ACTION,
        draft.entryId,
        withStreet(draft),
      ),
    ).rejects.toThrow();
    expect(await onDevice(store)).toBe(true);
    await queue.discard(draft.entryId);
    expect(await store.list()).toEqual([]);
  });

  it("goes when the draft expires after 14 days", async () => {
    const { queue, store } = controller();
    const draft = await draftWithContact(queue);
    const silent = {
      resolveSponsorMatch: () =>
        Promise.reject(new TypeError("Failed to fetch")),
    } as unknown as LeonAidApiClient;
    await expect(
      resolveDraftSponsor(
        silent,
        queue,
        ACTION,
        draft.entryId,
        withStreet(draft),
      ),
    ).rejects.toThrow();
    const later = new Date(Date.parse(draft.capturedAt) + 15 * 86_400_000);
    await drainQueue({
      now: () => later,
      send: () => Promise.reject(new Error("no send")),
      store,
    });
    const expired = (await store.list()).find(
      (entry) => entry.entryId === draft.entryId,
    ) as SponsorDraftEntry;
    expect(expired.state).toBe("expired");
    expect(expired.resolveRequest).toBeNull();
    expect(await onDevice(store)).toBe(false);
  });

  it("goes after 14 days from a blocked draft too, which itself stays (#139 M1)", async () => {
    const { queue, store } = controller();
    const draft = await draftWithContact(queue);
    const silent = {
      resolveSponsorMatch: () =>
        Promise.reject(new TypeError("Failed to fetch")),
    } as unknown as LeonAidApiClient;
    await expect(
      resolveDraftSponsor(
        silent,
        queue,
        ACTION,
        draft.entryId,
        withStreet(draft),
      ),
    ).rejects.toThrow();
    // A 403 for the action made every entry of it "Nicht mehr möglich".
    for (const entry of await store.list()) {
      await store.put({ ...entry, state: "blocked" });
    }
    const run = (days: number) =>
      drainQueue({
        now: () => new Date(Date.parse(draft.capturedAt) + days * 86_400_000),
        send: () => Promise.reject(new Error("no send")),
        store,
      });
    // Still within 14 days: the check may come back with the role, and its
    // replay needs the exact body.
    await run(13);
    expect(await onDevice(store)).toBe(true);
    await run(15);
    const blocked = (await store.list()).find(
      (entry) => entry.entryId === draft.entryId,
    ) as SponsorDraftEntry;
    expect(blocked.state).toBe("blocked");
    expect(blocked.resolveRequest).toBeNull();
    expect(blocked.resolution).toBeNull();
    expect(await onDevice(store)).toBe(false);
  });
});
