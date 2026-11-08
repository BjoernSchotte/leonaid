/*
 * The capture queue of the acquisition PWA (specs/pwa-offline-queue §9):
 * entries, their states, the order of sending, the classification of
 * Core's answers and the backoff. Pure logic over a QueueStore; the
 * browser's IndexedDB store and an in-memory store implement it.
 */
import {
  ApiError,
  type ResolveSponsorMatchRequest,
  type SponsorDraftRequest,
  type SponsorResolutionResponse,
  type CommitmentResponse,
  type CompleteCommitmentRequest,
  type CreateCommitmentRequest,
  type RecordAcquisitionActivityRequest,
  type RecordAcquisitionActivityResponse,
} from "@leonaid/api-client";

import type { DeviceStore } from "./device-store";

export type QueueKind =
  | "activity"
  | "commitment"
  | "commitment-completion"
  | "sponsor-draft";

/**
 * §9.3. `queued` waits for the network or its backoff; `sending` is in
 * flight (after a crash it is sent again with the same key); `conflict`
 * needs the acquirer's decision; `failed` is not resent automatically;
 * `expired` is past 14 days (D5); `blocked` is "Nicht mehr möglich" (403).
 */
export type QueueState =
  | "queued"
  | "sending"
  | "conflict"
  | "failed"
  | "expired"
  | "blocked";

export interface QueueParty {
  readonly kind: "company" | "person";
  readonly id: string;
  readonly displayName: string;
}

export interface QueueBase {
  readonly assignmentRevision?: number;
  readonly unitPriceMinor?: number;
  readonly windowId?: string | null;
  readonly windowFullyBooked?: boolean;
}

export interface QueueError {
  readonly code: string;
  readonly status: number;
  readonly message?: string;
  readonly details?: Record<string, unknown> | null;
}

interface EntryCommon {
  readonly entryId: string;
  readonly sequence: number;
  readonly actionId: string;
  readonly party: QueueParty;
  readonly assignmentId: string;
  readonly dependsOn: string | null;
  readonly idempotencyKey: string;
  /** Earlier keys of this capture, kept for support (§9.3). */
  readonly previousKeys: readonly string[];
  readonly capturedAt: string;
  readonly base: QueueBase;
  readonly state: QueueState;
  readonly attempts: number;
  /**
   * A send of this body left the device at least once (it may be at
   * Core). Such an entry is never rebased, never refused by a pre-send
   * check and never expired while Core may still replay it.
   */
  readonly everSent?: boolean;
  readonly nextAttemptAt: string | null;
  readonly lastError: QueueError | null;
  /** When the entry became `expired` or `blocked`; deleted 2 days later. */
  readonly settledAt: string | null;
  /** Core's view when a conflict needs it (e.g. a colleague's follow-up). */
  readonly conflictAssignment?: {
    readonly revision: number;
    readonly priority: number;
    readonly nextAction: string | null;
    readonly dueAt: string | null;
    readonly status: string;
  } | null;
}

export interface ActivityEntry extends EntryCommon {
  readonly kind: "activity";
  readonly request: RecordAcquisitionActivityRequest;
}

export interface CommitmentEntry extends EntryCommon {
  readonly kind: "commitment";
  readonly request: CreateCommitmentRequest;
}

export interface CompletionEntry extends EntryCommon {
  readonly kind: "commitment-completion";
  readonly commitmentId: string;
  readonly request: CompleteCommitmentRequest;
}

/**
 * A new sponsor saved offline (§10.4, D10). It never sends itself: the
 * acquirer resolves it online with the match step; entries that depend
 * on it wait (`dependsOn`) and then take the resolved sponsor.
 */
export interface SponsorDraftEntry extends EntryCommon {
  readonly kind: "sponsor-draft";
  /** The `command_id` of `resolveSponsorMatch` for this draft (§10.4). */
  readonly commandId: string;
  /**
   * The exact resolve body sent under `commandId`, kept before it goes out:
   * Core replays only that body (#132 N1). `null`: none sent, or refused.
   */
  readonly resolveRequest?: ResolveSponsorMatchRequest | null;
  /** Core's answer to that resolve, once it arrived. */
  readonly resolution?: SponsorResolutionResponse | null;
  readonly mode: "company" | "person";
  readonly request: SponsorDraftRequest;
}

export type QueueEntry =
  | ActivityEntry
  | CommitmentEntry
  | CompletionEntry
  | SponsorDraftEntry;

export interface QueueStore {
  list(): Promise<QueueEntry[]>;
  put(entry: QueueEntry): Promise<void>;
  delete(entryId: string): Promise<void>;
}

/** The browser implementation: sealed records in the user's database. */
export class DeviceQueueStore implements QueueStore {
  readonly #device: DeviceStore;

  constructor(device: DeviceStore) {
    this.#device = device;
  }

  async list(): Promise<QueueEntry[]> {
    return (await this.#device.queueRecords<QueueEntry>()).map(
      (record) => record.value,
    );
  }

  put(entry: QueueEntry): Promise<void> {
    return this.#device.putQueueRecord(
      {
        actionId: entry.actionId,
        dependsOn: entry.dependsOn ?? "",
        entryId: entry.entryId,
        sequence: entry.sequence,
        state: entry.state,
      },
      entry,
    );
  }

  delete(entryId: string): Promise<void> {
    return this.#device.deleteQueueRecord(entryId);
  }
}

/** A complete QueueStore in memory, for one page life or for tests. */
export class MemoryQueueStore implements QueueStore {
  readonly #entries = new Map<string, QueueEntry>();

  async list(): Promise<QueueEntry[]> {
    return [...this.#entries.values()].sort((a, b) => a.sequence - b.sequence);
  }

  async put(entry: QueueEntry): Promise<void> {
    for (const other of this.#entries.values()) {
      if (
        other.entryId !== entry.entryId &&
        other.sequence === entry.sequence
      ) {
        throw new Error("Queue sequence must be unique");
      }
    }
    this.#entries.set(entry.entryId, structuredClone(entry));
  }

  async delete(entryId: string): Promise<void> {
    this.#entries.delete(entryId);
  }
}

/* ---------- retention (D5, §8.5) ---------- */

const DAY_MS = 86_400_000;
export const QUEUE_KEEP_DAYS = 14;
export const SETTLED_KEEP_DAYS = 2;
export const MAX_UNKNOWN_ATTEMPTS = 5;
export const SEND_TIMEOUT_MS = 15_000;

/**
 * D5: an entry past 14 days expires, and an expired entry is deleted 2 days
 * after the warning. An entry that may already be at Core (`everSent`)
 * keeps trying until the end of those 2 days, so Core can replay it (the
 * receipt comes before the 14-day bound, §11.1). Nothing else is deleted
 * without the acquirer: "Nicht mehr möglich" waits for "Verwerfen".
 */
export function retention(
  entry: QueueEntry,
  now: Date,
): "keep" | "expire" | "delete" {
  if (entry.state === "expired") {
    const settled = Date.parse(entry.settledAt ?? entry.capturedAt);
    return now.getTime() - settled > SETTLED_KEEP_DAYS * DAY_MS
      ? "delete"
      : "keep";
  }
  if (entry.state === "sending" || entry.state === "blocked") return "keep";
  const age = now.getTime() - Date.parse(entry.capturedAt);
  const limit = entry.everSent
    ? (QUEUE_KEEP_DAYS + SETTLED_KEEP_DAYS) * DAY_MS
    : QUEUE_KEEP_DAYS * DAY_MS;
  return age > limit ? "expire" : "keep";
}

/* ---------- ordering (§9.2) ---------- */

export function partyKey(entry: QueueEntry) {
  return `${entry.party.kind}:${entry.party.id}`;
}

/** States that hold back later entries of the same sponsor. */
const HOLDS_SPONSOR: ReadonlySet<QueueState> = new Set([
  "queued",
  "sending",
  "conflict",
  "failed",
]);

/**
 * Order conflicts about the delivery window concern only that order: the
 * sponsor's later contacts and orders go on (their base does not depend
 * on it).
 */
const ORDER_ONLY_CONFLICTS: ReadonlySet<string> = new Set([
  "delivery_window_full",
  "delivery_window_unavailable",
  "delivery_required",
  "delivery_address_required",
  "delivery_window_required",
  "commitment_price_changed",
  "offering_not_available",
]);

function holdsSponsor(entry: QueueEntry): boolean {
  if (!HOLDS_SPONSOR.has(entry.state)) return false;
  return !(
    entry.state === "conflict" &&
    entry.kind === "commitment" &&
    ORDER_ONLY_CONFLICTS.has(entry.lastError?.code ?? "")
  );
}

/**
 * The next entry to send now: per sponsor in `sequence` order, one at a
 * time. An unresolved entry holds back only later entries of its own
 * sponsor; expired and blocked entries never send and hold nothing.
 */
export function nextSendable(
  entries: readonly QueueEntry[],
  now: Date,
): QueueEntry | null {
  const held = new Set<string>();
  const ordered = [...entries].sort((a, b) => a.sequence - b.sequence);
  for (const entry of ordered) {
    const key = partyKey(entry);
    if (held.has(key)) continue;
    if (holdsSponsor(entry)) held.add(key);
    if (entry.state !== "queued" && entry.state !== "sending") continue;
    if (entry.dependsOn || entry.kind === "sponsor-draft") continue;
    if (
      entry.state === "queued" &&
      entry.nextAttemptAt &&
      Date.parse(entry.nextAttemptAt) > now.getTime()
    ) {
      continue;
    }
    return entry;
  }
  return null;
}

/** When the next backoff timer is due, if any entry waits for one. */
export function nextDueAt(entries: readonly QueueEntry[]): number | null {
  const due = entries
    .filter((entry) => entry.state === "queued" && entry.nextAttemptAt)
    .map((entry) => Date.parse(entry.nextAttemptAt!));
  return due.length ? Math.min(...due) : null;
}

/* ---------- backoff (§9.4) ---------- */

/** 2 s, 4 s, 8 s … capped at 5 minutes, ±20 % jitter. */
export function backoffDelay(attempts: number, random: () => number) {
  const base = Math.min(2_000 * 2 ** Math.max(0, attempts - 1), 300_000);
  const jitter = 1 + (random() * 0.4 - 0.2);
  return Math.round(base * jitter);
}

/* ---------- classification (§9.4) ---------- */

/** Codes that need the acquirer's decision (§10). */
export const CONFLICT_CODES: ReadonlySet<string> = new Set([
  "assignment_revision_conflict",
  "contact_suppressed",
  "delivery_window_full",
  "delivery_window_unavailable",
  "delivery_required",
  "delivery_address_required",
  "delivery_window_required",
  "commitment_price_changed",
  "commitment_client_quote_required",
  "offering_not_available",
  "commitment_ordering_disabled",
  "commitment_action_closed",
  "captured_at_out_of_range",
]);

export type SendOutcome =
  | { readonly type: "accepted" }
  | { readonly type: "transient"; readonly retryAfterMs: number }
  | { readonly type: "paused" }
  | { readonly type: "blocked"; readonly error: QueueError }
  | { readonly type: "conflict"; readonly error: QueueError }
  | { readonly type: "failed"; readonly error: QueueError }
  | { readonly type: "unknown"; readonly error: QueueError };

function queueError(error: ApiError): QueueError {
  return {
    code: error.detail.code,
    details: error.detail.details ?? null,
    message: error.detail.message,
    status: error.status,
  };
}

/** 403 codes that mean "no longer allowed in this action" (§9.4). */
export const ACTION_FORBIDDEN_CODES: ReadonlySet<string> = new Set([
  "acquirer_required",
  "commitment_capture_required",
  "commitment_acquisition_required",
]);

/** 403 codes about this one sponsor or order, not the action. */
const ENTRY_FORBIDDEN_CODES: ReadonlyMap<string, string> = new Map([
  ["commitment_party_not_assigned", "sponsor_not_assigned"],
  ["commitment_owner_required", "commitment_owner_required"],
  ["commitment_source_forbidden", "commitment_source_forbidden"],
]);

/**
 * 403 codes of the transport guards (origin, CSRF): a session or
 * configuration problem, never a reason to give a capture up.
 */
const TRANSPORT_FORBIDDEN_CODES: ReadonlySet<string> = new Set([
  "csrf_rejected",
  "cors_origin_rejected",
]);

/** Maps a failed send to what the queue does next. */
export function classifyFailure(error: unknown): SendOutcome {
  if (!(error instanceof ApiError)) {
    return { type: "transient", retryAfterMs: 0 };
  }
  const status = error.status;
  const code = error.detail.code;
  // §9.4: at least Retry-After (429, and 503 for maintenance).
  const retryAfterMs = Math.max(0, error.retryAfterSeconds ?? 0) * 1000;
  if (
    status === 429 ||
    status === 502 ||
    status === 503 ||
    status === 504 ||
    code === "unexpected_response_type"
  ) {
    return { type: "transient", retryAfterMs };
  }
  if (status === 409 && code === "idempotency_incomplete") {
    return { type: "transient", retryAfterMs: 0 };
  }
  if (status === 401) return { type: "paused" };
  if (status === 403) {
    if (TRANSPORT_FORBIDDEN_CODES.has(code)) {
      return { type: "transient", retryAfterMs: 0 };
    }
    if (ACTION_FORBIDDEN_CODES.has(code)) {
      return { type: "blocked", error: queueError(error) };
    }
    const entryCode = ENTRY_FORBIDDEN_CODES.get(code);
    if (entryCode) {
      return {
        type: "conflict",
        error: { ...queueError(error), code: entryCode },
      };
    }
    return { type: "unknown", error: queueError(error) };
  }
  if (status === 404) {
    return {
      type: "conflict",
      error: { ...queueError(error), code: "sponsor_not_assigned" },
    };
  }
  if (status === 409 && code === "idempotency_conflict") {
    return { type: "failed", error: queueError(error) };
  }
  if ((status === 409 || status === 422) && CONFLICT_CODES.has(code)) {
    return { type: "conflict", error: queueError(error) };
  }
  return { type: "unknown", error: queueError(error) };
}

/* ---------- accepted answers (§9.2 base revision rule) ---------- */

export type SendResult =
  | {
      readonly kind: "activity";
      readonly response: RecordAcquisitionActivityResponse;
    }
  | { readonly kind: "commitment"; readonly response: CommitmentResponse };

/**
 * After an accepted activity, later activities of the same sponsor move
 * their base to the revision this send produced, and only when the
 * assignment was updated. `assignment.revision` is never taken: on a
 * replay or a kept contact it may hold someone else's change.
 */
export function rebaseAfter(
  accepted: QueueEntry,
  response: RecordAcquisitionActivityResponse,
  entries: readonly QueueEntry[],
): QueueEntry[] {
  if (response.assignmentUpdated === false) return [];
  const revision = response.activity.assignmentRevision;
  return entries
    .filter(
      (entry): entry is ActivityEntry =>
        entry.kind === "activity" &&
        entry.entryId !== accepted.entryId &&
        entry.sequence > accepted.sequence &&
        partyKey(entry) === partyKey(accepted) &&
        entry.state === "queued" &&
        !entry.everSent,
    )
    .map((entry) => ({
      ...entry,
      base: { ...entry.base, assignmentRevision: revision },
      request: { ...entry.request, revision },
    }));
}

export function newEntryId(): string {
  return crypto.randomUUID();
}

export function idempotencyKeyFor(entryId: string): string {
  return `pwa-q:${entryId}`;
}

/** The device time with its offset, as Core expects `capturedAt`. */
export function capturedAtNow(now: Date = new Date()): string {
  const offset = -now.getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  const hours = String(Math.floor(Math.abs(offset) / 60)).padStart(2, "0");
  const minutes = String(Math.abs(offset) % 60).padStart(2, "0");
  const local = new Date(now.getTime() + offset * 60_000)
    .toISOString()
    .slice(0, 23);
  return `${local}${sign}${hours}:${minutes}`;
}
