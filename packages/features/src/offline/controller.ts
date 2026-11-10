/*
 * The capture queue as the page uses it (specs/pwa-offline-queue §9.1):
 * write a capture, send it at once when online, retry on `online`, focus,
 * visibility and a backoff timer, and keep every tab's view current. One
 * tab sends at a time (Web Lock); the others follow over a
 * BroadcastChannel and re-read the store.
 */
import { drainQueue, type SyncDependencies, type SyncReport } from "./sync";
import type {
  DeliveryStateRequest,
  SponsorDraftRequest,
} from "@leonaid/api-client";

import {
  capturedAtNow,
  deliveryTarget,
  idempotencyKeyFor,
  nextDueAt,
  newEntryId,
  sameAction,
  type DeliveryStateEntry,
  type DeliveryTarget,
  type QueueEntry,
  type QueueError,
  type QueueStore,
  type SendResult,
  type SponsorDraftEntry,
  type TourOrderEntry,
} from "./queue";

/**
 * "Meine Tour" offline: what changed with the queue (§9). `queued`: an
 * entry waits to be sent; `cleared`: an unsent entry was taken back (the
 * stop or order is as Core has it); `unchanged`: nothing to do.
 */
export type TourWriteOutcome = "queued" | "cleared" | "unchanged";

function sameOrder(a: readonly string[], b: readonly string[]) {
  return a.length === b.length && a.every((id, index) => id === b[index]);
}

/** Not sent yet and not in flight: its body may still change or go. */
function replaceable(entry: QueueEntry) {
  return entry.state === "queued" && !entry.everSent;
}

/** What the page fills in; the controller adds the bookkeeping. */
export type QueueDraft = QueueEntry extends infer Entry
  ? Entry extends QueueEntry
    ? Omit<
        Entry,
        | "entryId"
        | "sequence"
        | "idempotencyKey"
        | "previousKeys"
        | "capturedAt"
        | "state"
        | "attempts"
        | "nextAttemptAt"
        | "lastError"
        | "settledAt"
        | "dependsOn"
      > & {
        readonly capturedAt?: string;
        /** The sponsor draft this capture waits for (§9.2). */
        readonly dependsOn?: string | null;
      }
    : never
  : never;

export type SubmitOutcome =
  | {
      readonly state: "accepted";
      readonly entryId: string;
      readonly result: SendResult;
    }
  | {
      /** Another tab sent it meanwhile; Core has it. */
      readonly state: "sent";
      readonly entryId: string;
    }
  | {
      readonly state: "queued" | "conflict" | "failed" | "blocked" | "expired";
      readonly entryId: string;
      readonly error: QueueError | null;
      /** Why a queued entry is still here: no network, signed out, or a retry. */
      readonly reason?: "offline" | "paused" | "retry";
    };

export interface QueueSnapshot {
  readonly entries: readonly QueueEntry[];
  readonly sending: boolean;
  /** A 401 paused the queue until the same user signs in again (§8.5). */
  readonly paused: boolean;
  /** Accepted in this page life; shown as "Gesendet" (§8.5). */
  readonly sent: readonly QueueEntry[];
  /** navigator.storage.persist() refused: the browser may evict (§8.5). */
  readonly evictable: boolean;
  /** The store has been read once (drafts and counts are real). */
  readonly loaded: boolean;
}

export interface QueueControllerOptions {
  readonly store: QueueStore;
  readonly userId: string;
  readonly send: SyncDependencies["send"];
  readonly preflight?: SyncDependencies["preflight"];
  readonly sendRecords?: SyncDependencies["sendRecords"];
  /** After accepted entries: refresh the read cache and the pages. */
  readonly onAccepted?: (report: SyncReport) => void;
  readonly now?: () => Date;
}

type Listener = (snapshot: QueueSnapshot) => void;

/**
 * "Gesendet" lives for this page only (§8.5), across the controllers a
 * page goes through (offline start, then online with fresh storage).
 */
const sentThisPage = new Map<string, readonly QueueEntry[]>();

export class QueueController {
  readonly #options: QueueControllerOptions;
  readonly #listeners = new Set<Listener>();
  readonly #channel: BroadcastChannel | null;
  #snapshot: QueueSnapshot = {
    entries: [],
    evictable: false,
    loaded: false,
    paused: false,
    sending: false,
    sent: [],
  };
  #timer: ReturnType<typeof setTimeout> | null = null;
  #chain: Promise<unknown> = Promise.resolve();
  #running: Promise<SyncReport | null> | null = null;
  #rerun = false;
  #stopped = false;
  #accepted = new Map<string, SendResult>();
  #persistAsked = false;

  constructor(options: QueueControllerOptions) {
    this.#options = options;
    this.#channel =
      typeof BroadcastChannel === "function"
        ? new BroadcastChannel(`leonaid-queue-${options.userId}`)
        : null;
    if (this.#channel) {
      this.#channel.onmessage = () => void this.reload();
    }
  }

  get snapshot(): QueueSnapshot {
    return this.#snapshot;
  }

  subscribe(listener: Listener): () => void {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }

  #publish(partial: Partial<QueueSnapshot>) {
    this.#snapshot = { ...this.#snapshot, ...partial };
    for (const listener of this.#listeners) listener(this.#snapshot);
  }

  #announce() {
    this.#channel?.postMessage("changed");
  }

  async reload(): Promise<void> {
    if (this.#stopped) return;
    // The store can be gone (sign-out in another tab): keep the last view.
    const entries = await this.#options.store.list().catch(() => null);
    if (!entries) return;
    this.#publish({
      entries,
      loaded: true,
      sent: sentThisPage.get(this.#options.userId) ?? [],
    });
    this.#schedule(entries);
  }

  /** Saves a capture on the device; online it is sent at once. */
  async submit(draft: QueueDraft): Promise<SubmitOutcome> {
    const entry = await this.#write(draft);
    return this.#sendAndReport(entry.entryId);
  }

  /**
   * An online decision on the capture page (FullWindowConfirm, the new
   * price, an edited order): the entry changes and is sent again at once
   * (§10.2). `null`: the entry is gone (discarded in the queue meanwhile).
   */
  async resubmit(
    entryId: string,
    change: (entry: QueueEntry) => QueueEntry,
    options: { readonly newKey: boolean },
  ): Promise<SubmitOutcome | null> {
    const applied = await this.replace(entryId, change, options);
    if (applied === "missing") return null;
    return this.#sendAndReport(entryId);
  }

  async #sendAndReport(entryId: string): Promise<SubmitOutcome> {
    if (navigator.onLine === false || this.#snapshot.paused) {
      return {
        entryId,
        error: null,
        reason: this.#snapshot.paused ? "paused" : "offline",
        state: "queued",
      };
    }
    await this.run();
    // A run already under way when the entry was written ends with a rerun.
    while (this.#running) await this.#running;
    const result = this.#accepted.get(entryId);
    if (result) return { entryId, result, state: "accepted" };
    const current = (await this.#options.store.list()).find(
      (item) => item.entryId === entryId,
    );
    if (!current) return { entryId, state: "sent" };
    if (current.state === "sending" || current.state === "queued") {
      return {
        entryId,
        error: current.lastError,
        reason: this.#snapshot.paused ? "paused" : "retry",
        state: "queued",
      };
    }
    return { entryId, error: current.lastError, state: current.state };
  }

  /** A new entry of `draft` with the bookkeeping, numbered after `existing`. */
  #build(
    draft: QueueDraft,
    entryId: string,
    existing: readonly QueueEntry[],
    attempt: number,
  ): QueueEntry {
    const now = this.#options.now?.() ?? new Date();
    const highest = existing.reduce(
      (max, item) => Math.max(max, item.sequence),
      0,
    );
    return {
      ...draft,
      attempts: 0,
      capturedAt: draft.capturedAt ?? capturedAtNow(now),
      dependsOn: draft.dependsOn ?? null,
      entryId,
      idempotencyKey: idempotencyKeyFor(entryId),
      lastError: null,
      nextAttemptAt: null,
      previousKeys: [],
      sequence: Math.max(highest + 1, now.getTime()) + attempt,
      settledAt: null,
      state: "queued",
    } as QueueEntry;
  }

  async #write(
    draft: QueueDraft,
    entryId: string = newEntryId(),
  ): Promise<QueueEntry> {
    const { store } = this.#options;
    for (let attempt = 0; ; attempt += 1) {
      const entry = this.#build(draft, entryId, await store.list(), attempt);
      try {
        await store.put(entry);
        await this.#askPersistence();
        this.#announce();
        await this.reload();
        return entry;
      } catch (error) {
        // Another tab took the same sequence number: take the next.
        if (attempt >= 5) throw error;
      }
    }
  }

  /**
   * Writes a driver's entry under the sending lock: `decide` sees the store
   * and returns the entry to keep, an entry to delete, or nothing to do.
   */
  async #tourWrite(
    decide: (
      entries: readonly QueueEntry[],
    ) =>
      | { readonly put: QueueEntry }
      | { readonly delete: string }
      | { readonly add: QueueDraft }
      | null,
  ): Promise<TourWriteOutcome> {
    let outcome = "unchanged" as TourWriteOutcome;
    await this.#mutate(async (store) => {
      const entries = await store.list();
      const decision = decide(entries);
      if (!decision) return;
      if ("delete" in decision) {
        await store.delete(decision.delete);
        outcome = "cleared";
        return;
      }
      outcome = "queued";
      if ("put" in decision) {
        await store.put(decision.put);
        return;
      }
      for (let attempt = 0; ; attempt += 1) {
        try {
          await store.put(
            this.#build(decision.add, newEntryId(), entries, attempt),
          );
          return;
        } catch (error) {
          if (attempt >= 5) throw error;
        }
      }
    });
    if (outcome === "queued") await this.#askPersistence();
    void this.run();
    return outcome;
  }

  /**
   * "Zugestellt", "Nicht da" or "Rückgängig" of a stop, through the queue
   * (krapfentaxi-touren §9). A pending mark of the stop that was not sent
   * yet takes the new target; one that goes back to the state it started
   * from is deleted ("cleared"). `fromState` and `expectedRevision` are the
   * stop as the driver sees it.
   */
  queueDeliveryState(draft: {
    readonly actionId: string;
    readonly commitmentId: string;
    readonly displayName: string;
    readonly fromState: DeliveryTarget;
    readonly target: DeliveryTarget;
    readonly expectedRevision: number;
  }): Promise<TourWriteOutcome> {
    const request: DeliveryStateRequest = {
      delivered: draft.target === "delivered",
      expectedRevision: draft.expectedRevision,
      missed: draft.target === "missed",
    };
    const now = this.#options.now?.() ?? new Date();
    return this.#tourWrite((entries) => {
      const pending = entries.find(
        (entry): entry is DeliveryStateEntry =>
          entry.kind === "delivery-state" &&
          sameAction(entry.actionId, draft.actionId) &&
          entry.commitmentId === draft.commitmentId &&
          replaceable(entry),
      );
      if (pending) {
        if (draft.target === pending.fromState) {
          return { delete: pending.entryId };
        }
        if (draft.target === deliveryTarget(pending.request)) return null;
        // Never sent: the body may change under the same key.
        return {
          put: {
            ...pending,
            capturedAt: capturedAtNow(now),
            request: {
              ...request,
              expectedRevision: pending.request.expectedRevision,
            },
          },
        };
      }
      if (draft.target === draft.fromState) return null;
      return {
        add: {
          actionId: draft.actionId,
          assignmentId: "",
          base: {},
          commitmentId: draft.commitmentId,
          fromState: draft.fromState,
          kind: "delivery-state",
          party: {
            displayName: draft.displayName,
            id: `stop:${draft.commitmentId}`,
            kind: "person",
          },
          request,
        },
      };
    });
  }

  /**
   * One move of the driver's order, through the queue (§9). A pending
   * order of the same action and day that was not sent yet takes the new
   * order; back at the order it started from it is deleted.
   *
   * `everSent`: the order already went out once (an online save that got no
   * answer) and may be at Core. It becomes an entry of its own, never merged,
   * so later moves queue behind it and take the revision Core returns for it
   * (`rebaseTourEntries`).
   */
  queueTourOrder(draft: {
    readonly actionId: string;
    readonly day: string;
    readonly displayName: string;
    readonly fromOrder: readonly string[];
    readonly commitmentIds: readonly string[];
    readonly expectedRevision: string;
    readonly everSent?: boolean;
  }): Promise<TourWriteOutcome> {
    const now = this.#options.now?.() ?? new Date();
    return this.#tourWrite((entries) => {
      const pending = draft.everSent
        ? undefined
        : entries.find(
            (entry): entry is TourOrderEntry =>
              entry.kind === "tour-order" &&
              sameAction(entry.actionId, draft.actionId) &&
              entry.request.day === draft.day &&
              replaceable(entry),
          );
      if (pending) {
        if (sameOrder(draft.commitmentIds, pending.fromOrder)) {
          return { delete: pending.entryId };
        }
        if (sameOrder(draft.commitmentIds, pending.request.commitmentIds)) {
          return null;
        }
        return {
          put: {
            ...pending,
            capturedAt: capturedAtNow(now),
            request: {
              ...pending.request,
              commitmentIds: [...draft.commitmentIds],
            },
          },
        };
      }
      if (sameOrder(draft.commitmentIds, draft.fromOrder)) return null;
      return {
        add: {
          actionId: draft.actionId,
          assignmentId: "",
          base: {},
          fromOrder: [...draft.fromOrder],
          ...(draft.everSent ? { everSent: true } : {}),
          kind: "tour-order",
          party: {
            displayName: draft.displayName,
            id: `tour:${draft.actionId}:${draft.day}`,
            kind: "person",
          },
          request: {
            commitmentIds: [...draft.commitmentIds],
            day: draft.day,
            expectedRevision: draft.expectedRevision,
          },
        },
      };
    });
  }

  /** The entry changes content: new body, new key, the old key kept. */
  async replace(
    entryId: string,
    change: (entry: QueueEntry) => QueueEntry,
    { newKey }: { readonly newKey: boolean },
  ): Promise<"applied" | "missing" | "sending"> {
    let applied: "applied" | "missing" | "sending" = "missing";
    await this.#mutate(async (store) => {
      const current = (await store.list()).find(
        (item) => item.entryId === entryId,
      );
      if (!current) return;
      // In flight in another tab: its answer decides; nothing changes.
      if (current.state === "sending") {
        applied = "sending";
        return;
      }
      applied = "applied";
      const changed = change(current);
      await store.put({
        ...changed,
        attempts: 0,
        // A new body is a new command (§9.3): new key, never sent yet.
        everSent: newKey ? false : current.everSent,
        idempotencyKey: newKey
          ? idempotencyKeyFor(newEntryId())
          : current.idempotencyKey,
        lastError: null,
        nextAttemptAt: null,
        previousKeys: newKey
          ? [...current.previousKeys, current.idempotencyKey]
          : current.previousKeys,
        state: "queued",
      } as QueueEntry);
    });
    void this.run();
    return applied;
  }

  /**
   * Deletes an entry. It waits for a send in flight (same lock), so a
   * discarded entry never reaches Core afterwards nor comes back. A draft
   * goes with the captures that wait for it (§10.4), read from the store,
   * so one written in another tab is not left behind.
   */
  async discard(
    entryId: string,
    shownDependents?: readonly string[],
  ): Promise<"discarded" | "changed"> {
    let outcome: "discarded" | "changed" = "discarded";
    await this.#mutate(async (store) => {
      const dependents = (await store.list()).filter(
        (entry) => entry.dependsOn === entryId,
      );
      // A capture the confirmation did not name (written in another tab
      // meanwhile) is never deleted unseen: the sheet asks again (#132 N2).
      if (
        shownDependents &&
        dependents.some((entry) => !shownDependents.includes(entry.entryId))
      ) {
        outcome = "changed";
        return;
      }
      for (const entry of dependents) await store.delete(entry.entryId);
      await store.delete(entryId);
    });
    void this.run();
    return outcome;
  }

  /** A new sponsor saved offline (§10.4); never sent by itself. */
  async saveDraft({
    actionId,
    mode,
    request,
  }: {
    readonly actionId: string;
    readonly mode: "company" | "person";
    readonly request: SponsorDraftRequest;
  }): Promise<SponsorDraftEntry> {
    const entryId = newEntryId();
    const placeholder = `draft:${entryId}`;
    const displayName =
      mode === "company"
        ? (request.companyName ?? "").trim()
        : [request.givenName, request.familyName]
            .filter(Boolean)
            .join(" ")
            .trim();
    return (await this.#write(
      {
        actionId,
        assignmentId: placeholder,
        base: {},
        // §10.4: the match step resolves with the draft's own command id,
        // so a repeated check after a lost answer replays, not duplicates.
        commandId: newEntryId(),
        kind: "sponsor-draft",
        mode,
        party: { displayName, id: placeholder, kind: mode },
        request,
      },
      entryId,
    )) as SponsorDraftEntry;
  }

  /**
   * The match step resolved a draft: the captures that waited for it take
   * the sponsor, assignment and revision Core returned and are sent (§9.2).
   */
  async resolveDraft(
    draftId: string,
    resolved: {
      readonly partyKind: "company" | "person";
      readonly partyId: string;
      readonly displayName: string;
      readonly assignmentId: string;
      readonly revision: number;
    },
  ): Promise<void> {
    const party = {
      displayName: resolved.displayName,
      id: resolved.partyId,
      kind: resolved.partyKind,
    };
    await this.#mutate(async (store) => {
      for (const entry of await store.list()) {
        if (entry.dependsOn !== draftId) continue;
        if (entry.kind === "activity") {
          await store.put({
            ...entry,
            assignmentId: resolved.assignmentId,
            base: { ...entry.base, assignmentRevision: resolved.revision },
            dependsOn: null,
            party,
            request: {
              ...entry.request,
              partyId: resolved.partyId,
              partyKind: resolved.partyKind,
              revision: resolved.revision,
            },
          });
        } else {
          await store.put({
            ...entry,
            assignmentId: resolved.assignmentId,
            dependsOn: null,
            party,
          });
        }
      }
      await store.delete(draftId);
    });
    void this.run();
  }

  /** Updates a decision's facts (Core's current state); it stays put. */
  async annotate(
    entryId: string,
    patch: Pick<QueueEntry, "conflictAssignment">,
  ): Promise<void> {
    await this.#mutate(async (store) => {
      const current = (await store.list()).find(
        (item) => item.entryId === entryId,
      );
      if (current) await store.put({ ...current, ...patch } as QueueEntry);
    });
  }

  /** The captures that wait for a draft, as the store holds them. */
  async dependents(draftId: string): Promise<QueueEntry[]> {
    // Read under the lock: not between a writer's steps in another tab.
    return this.#exclusive(async () =>
      (await this.#options.store.list()).filter(
        (entry) => entry.dependsOn === draftId,
      ),
    );
  }

  /**
   * Keeps what a draft's CRM check sent and got (#132 N1), or gives the
   * draft a new command id after Core refused the check.
   */
  async updateDraft(
    draftId: string,
    patch: Partial<
      Pick<SponsorDraftEntry, "commandId" | "resolveRequest" | "resolution">
    >,
  ): Promise<void> {
    await this.#mutate(async (store) => {
      const current = (await store.list()).find(
        (item) => item.entryId === draftId,
      );
      if (current?.kind === "sponsor-draft") {
        await store.put({ ...current, ...patch });
      }
    });
  }

  /** "Erneut versuchen" of a failed or no-longer-possible entry. */
  async retry(entryId: string): Promise<void> {
    await this.#mutate(async (store) => {
      const current = (await store.list()).find(
        (item) => item.entryId === entryId,
      );
      if (!current || current.state === "sending") return;
      await store.put({
        ...current,
        attempts: 0,
        nextAttemptAt: null,
        settledAt: null,
        state: "queued",
      });
    });
    void this.run();
  }

  /** "Jetzt senden", `online` and a new sign-in reset the backoff. */
  async sendNow(): Promise<void> {
    this.#publish({ paused: false });
    await this.#mutate(async (store) => {
      for (const entry of await store.list()) {
        if (entry.state === "queued" && entry.nextAttemptAt) {
          await store.put({ ...entry, nextAttemptAt: null });
        }
      }
    });
    await this.run();
  }

  /** A change of the store under the sending lock, then the news. */
  async #mutate(change: (store: QueueStore) => Promise<void>): Promise<void> {
    await this.#exclusive(() => change(this.#options.store));
    this.#announce();
    await this.reload();
  }

  /**
   * One writer at a time: this page's runs and changes queue up in order,
   * and the Web Lock keeps other tabs out while one of them runs.
   */
  #exclusive<T>(work: () => Promise<T>): Promise<T> {
    const locks =
      typeof navigator !== "undefined" ? navigator.locks : undefined;
    const next = this.#chain.then(() =>
      locks
        ? (locks.request(
            `leonaid-sync-${this.#options.userId}`,
            work,
          ) as Promise<T>)
        : work(),
    );
    this.#chain = next.catch(() => undefined);
    return next;
  }

  /** Runs the loop under the user's Web Lock; one run at a time. */
  run(): Promise<SyncReport | null> {
    if (this.#stopped) return Promise.resolve(null);
    if (this.#running) {
      this.#rerun = true;
      return this.#running;
    }
    this.#running = this.#runLocked().finally(() => {
      this.#running = null;
      if (this.#rerun && !this.#stopped) {
        this.#rerun = false;
        void this.run();
      }
    });
    return this.#running;
  }

  async #runLocked(): Promise<SyncReport | null> {
    if (navigator.onLine === false || this.#snapshot.paused) {
      await this.reload();
      return null;
    }
    const work = async () => {
      this.#publish({ sending: true });
      try {
        const report = await drainQueue({
          now: this.#options.now,
          onProgress: async () => {
            this.#announce();
            await this.reload();
          },
          preflight: this.#options.preflight,
          sendRecords: this.#options.sendRecords,
          send: this.#options.send,
          store: this.#options.store,
        });
        for (const { entry, result } of report.accepted) {
          this.#accepted.set(entry.entryId, result);
        }
        if (report.accepted.length) {
          const sent = [
            ...(sentThisPage.get(this.#options.userId) ?? []),
            ...report.accepted.map(({ entry }) => entry),
          ];
          sentThisPage.set(this.#options.userId, sent);
          this.#publish({ sent });
          this.#options.onAccepted?.(report);
        }
        if (report.paused) this.#publish({ paused: true });
        return report;
      } finally {
        this.#publish({ sending: false });
        this.#announce();
        await this.reload();
      }
    };
    // Another tab (or this page's previous controller) may be sending: wait
    // for it, then drain what is left and read the store fresh. The holder
    // never keeps the lock longer than one drain (each send times out).
    return this.#exclusive(() =>
      this.#stopped ? Promise.resolve(null) : work(),
    );
  }

  #schedule(entries: readonly QueueEntry[]) {
    if (this.#timer) clearTimeout(this.#timer);
    this.#timer = null;
    const due = nextDueAt(entries);
    if (due === null || this.#stopped) return;
    const delay = Math.max(0, due - Date.now()) + 50;
    this.#timer = setTimeout(() => {
      this.#timer = null;
      // Only while visible (§9.4); `visibilitychange` restarts it.
      if (document.visibilityState === "visible") void this.run();
    }, delay);
  }

  async #askPersistence() {
    if (this.#persistAsked) return;
    this.#persistAsked = true;
    const storage = navigator.storage;
    if (!storage?.persist) return;
    try {
      const persisted =
        (await storage.persisted?.()) || (await storage.persist());
      this.#publish({ evictable: !persisted });
    } catch {
      this.#publish({ evictable: true });
    }
  }

  /** Starts the triggers of §9.1; returns the stop function. */
  start(): () => void {
    const onOnline = () => void this.sendNow();
    const onVisible = () => {
      if (document.visibilityState === "visible") void this.run();
    };
    window.addEventListener("online", onOnline);
    window.addEventListener("focus", onVisible);
    document.addEventListener("visibilitychange", onVisible);
    void this.reload().then(() => this.run());
    return () => {
      this.#stopped = true;
      if (this.#timer) clearTimeout(this.#timer);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("focus", onVisible);
      document.removeEventListener("visibilitychange", onVisible);
      this.#listeners.clear();
      // A send under way still tells the other tabs (and this page's next
      // controller) what it changed before the channel closes.
      const channel = this.#channel;
      void (this.#running ?? Promise.resolve(null)).finally(() =>
        channel?.close(),
      );
    };
  }
}
