/*
 * The sync loop of the capture queue (specs/pwa-offline-queue §9.1, §9.4):
 * one entry at a time, per sponsor in capture order, with the same key on
 * every send. The loop runs in the page (no Background Sync, G5); a Web
 * Lock in the browser keeps it to one tab.
 */
import {
  ApiError,
  type LeonAidApiClient,
  type RecordAcquisitionActivityResponse,
} from "@leonaid/api-client";

import {
  MAX_UNKNOWN_ATTEMPTS,
  SEND_TIMEOUT_MS,
  backoffDelay,
  classifyFailure,
  nextSendable,
  rebaseAfter,
  retention,
  type QueueEntry,
  type QueueStore,
  type SendResult,
} from "./queue";

export interface SyncDependencies {
  readonly store: QueueStore;
  /** One HTTP attempt for the entry; throws what the client throws. */
  readonly send: (entry: QueueEntry) => Promise<SendResult>;
  readonly now?: () => Date;
  readonly random?: () => number;
  /**
   * A decision known before sending (§10.3), e.g. the device copy shows
   * the chosen window as full; null sends.
   */
  readonly preflight?: (entry: QueueEntry) => Promise<string | null>;
}

export interface SyncReport {
  /** Entries Core accepted in this run, with Core's answer. */
  readonly accepted: ReadonlyArray<{
    readonly entry: QueueEntry;
    readonly result: SendResult;
  }>;
  /** A 401 paused the whole queue (§9.4). */
  readonly paused: boolean;
}

/** Retry-After of a 429, in seconds, carried on the API error if known. */
function retryAfter(error: unknown): number | null {
  if (!(error instanceof ApiError)) return null;
  const value = error.detail.details?.["retryAfterSeconds"];
  return typeof value === "number" ? value : null;
}

/**
 * Applies retention (D5) and sends every entry that is due, one after the
 * other. Returns when nothing is due now; a later backoff is the caller's
 * timer (nextDueAt).
 */
export async function drainQueue(
  dependencies: SyncDependencies,
): Promise<SyncReport> {
  const now = dependencies.now ?? (() => new Date());
  const random = dependencies.random ?? Math.random;
  const { store } = dependencies;
  const accepted: { entry: QueueEntry; result: SendResult }[] = [];

  for (const entry of await store.list()) {
    const rule = retention(entry, now());
    if (rule === "delete") await store.delete(entry.entryId);
    if (rule === "expire") {
      await store.put({
        ...entry,
        state: "expired",
        settledAt: now().toISOString(),
      });
    }
  }

  // Each loop sends one entry; a send changes what is due next.
  for (;;) {
    const entries = await store.list();
    const entry = nextSendable(entries, now());
    if (!entry) return { accepted, paused: false };
    const known = await dependencies.preflight?.(entry);
    if (known) {
      await store.put({
        ...entry,
        lastError: { code: known, message: "", status: 0 },
        nextAttemptAt: null,
        state: "conflict",
      });
      continue;
    }
    const sending: QueueEntry = { ...entry, state: "sending" };
    await store.put(sending);
    let result: SendResult;
    try {
      result = await dependencies.send(sending);
    } catch (error) {
      const outcome = classifyFailure(error, retryAfter(error));
      const attempts = entry.attempts + 1;
      switch (outcome.type) {
        case "transient": {
          const delay = Math.max(
            backoffDelay(attempts, random),
            outcome.retryAfterMs,
          );
          await store.put({
            ...entry,
            attempts,
            nextAttemptAt: new Date(now().getTime() + delay).toISOString(),
            state: "queued",
          });
          // No network or an overloaded Core: the other entries would
          // meet the same; the backoff timer starts the next run.
          return { accepted, paused: false };
        }
        case "paused":
          await store.put({ ...entry, state: "queued" });
          return { accepted, paused: true };
        case "blocked": {
          // 403: nothing of that action can be sent any more.
          const settledAt = now().toISOString();
          for (const other of await store.list()) {
            if (
              other.actionId === entry.actionId &&
              other.state !== "expired" &&
              other.state !== "blocked"
            ) {
              await store.put({
                ...other,
                lastError: outcome.error,
                settledAt,
                state: "blocked",
              });
            }
          }
          continue;
        }
        case "conflict":
        case "failed":
          await store.put({
            ...entry,
            attempts,
            lastError: outcome.error,
            nextAttemptAt: null,
            state: outcome.type,
          });
          continue;
        case "unknown":
          await store.put({
            ...entry,
            attempts,
            lastError: outcome.error,
            nextAttemptAt:
              attempts >= MAX_UNKNOWN_ATTEMPTS
                ? null
                : new Date(
                    now().getTime() + backoffDelay(attempts, random),
                  ).toISOString(),
            state: attempts >= MAX_UNKNOWN_ATTEMPTS ? "failed" : "queued",
          });
          continue;
      }
      continue;
    }
    await settleAccepted(store, entry, result);
    accepted.push({ entry, result });
  }
}

async function settleAccepted(
  store: QueueStore,
  entry: QueueEntry,
  result: SendResult,
) {
  if (result.kind === "activity") {
    const response: RecordAcquisitionActivityResponse = result.response;
    for (const rebased of rebaseAfter(entry, response, await store.list())) {
      await store.put(rebased);
    }
    if (response.assignmentUpdated === false && hasFollowUp(entry)) {
      // D1: the contact is stored, the follow-up was not applied because
      // the assignment moved; the acquirer decides (§10.1).
      await store.put({
        ...entry,
        conflictAssignment: {
          dueAt: response.assignment.dueAt,
          nextAction: response.assignment.nextAction,
          priority: response.assignment.priority,
          revision: response.assignment.revision,
          status: response.assignment.status,
        },
        lastError: {
          code: "follow_up_not_applied",
          message: "",
          status: 201,
        },
        nextAttemptAt: null,
        state: "conflict",
      });
      return;
    }
  }
  await store.delete(entry.entryId);
}

function hasFollowUp(entry: QueueEntry) {
  return (
    entry.kind === "activity" &&
    Boolean(entry.request.dueOn && entry.request.nextAction)
  );
}

/** Sends one entry through the generated client with the entry's key. */
export async function sendEntry(
  client: LeonAidApiClient,
  entry: QueueEntry,
): Promise<SendResult> {
  const options = {
    headers: { "Idempotency-Key": entry.idempotencyKey },
    signal: AbortSignal.timeout(SEND_TIMEOUT_MS),
  };
  switch (entry.kind) {
    case "activity":
      return {
        kind: "activity",
        response: await client.recordAcquisitionActivity(
          entry.actionId,
          { ...entry.request, capturedAt: entry.capturedAt },
          options,
        ),
      };
    case "commitment":
      return {
        kind: "commitment",
        response: await client.createCommitment(
          entry.actionId,
          { ...entry.request, capturedAt: entry.capturedAt },
          options,
        ),
      };
    case "commitment-completion":
      return {
        kind: "commitment",
        response: await client.completeCommitment(
          entry.actionId,
          entry.commitmentId,
          { ...entry.request, capturedAt: entry.capturedAt },
          options,
        ),
      };
    case "sponsor-draft":
      // nextSendable never offers a draft; the match step resolves it.
      throw new Error("A sponsor draft is resolved, not sent");
  }
}
