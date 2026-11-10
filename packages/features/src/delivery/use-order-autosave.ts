import { useEffect, useRef, useState } from "react";

import { useOptionalToast } from "@leonaid/ui";

/** Chained moves within this time go out as one save (spec D16). */
export const ORDER_SAVE_DELAY_MS = 600;
/** How long "Rückgängig" stays on the saved toast. */
export const ORDER_UNDO_MS = 10_000;

export interface OrderAutosaveOptions<T, C> {
  /**
   * Sends one order of the tour `key` with the revision the user saw, in
   * the context (day, action, query key) the move was made in.
   */
  readonly save: (
    key: string,
    ids: readonly string[],
    revision: string,
    context: C,
  ) => Promise<T>;
  readonly revisionOf: (saved: T) => string;
  /** The saved tour, to put into the query cache of its own context. */
  readonly onSaved: (key: string, saved: T, context: C) => void;
  /**
   * A failed save. The shown order is already back at the server's; say
   * why and reload when the tour changed meanwhile.
   */
  readonly onFailed: (key: string, error: unknown, context: C) => void;
  /**
   * A save that failed: true when the page kept the order another way (the
   * offline queue after a network failure). Then it is no failure: no
   * `onFailed`, and moves behind it still go out. `ids` is the burst's
   * latest order, `revision` and `confirmed` the revision and order Core
   * had when it was sent, `baseline` the order before its first move.
   */
  readonly divert?: (
    key: string,
    error: unknown,
    draft: {
      readonly ids: readonly string[];
      readonly revision: string;
      readonly confirmed: readonly string[];
      readonly baseline: readonly string[];
      readonly context: C;
      /** No toast: an undo replaced this save on screen. */
      readonly silent: boolean;
      /** The save was an undo: its toast offers no "Rückgängig". */
      readonly undo: boolean;
    },
  ) => Promise<boolean>;
  readonly savedText: (key: string, context: C) => string;
  readonly undoneText: (key: string, context: C) => string;
  readonly delayMs?: number;
}

interface Burst<C> {
  /** The order before the first move; "Rückgängig" restores it. */
  readonly baseline: readonly string[];
  /** Day, action and query key of the first move; every save uses them. */
  readonly context: C;
  /** The revision the next save sends; moves on with each own save. */
  revision: string;
  /** Core's order at `revision`: the baseline, then each saved order. */
  confirmed: readonly string[];
  ids: readonly string[];
  /** Bumped by each move; a save only settles the burst if none followed. */
  seq: number;
  sentSeq: number;
  timer: number | null;
  /** This burst is an undo: its toast has no "Rückgängig". */
  readonly undo: boolean;
  /**
   * Started while an own save of its tour was not through yet (an undo, a
   * move made while an undo waits, or a move after a switch back to a tour
   * whose released save still runs): its first save sends the revision the
   * last of them returned, and it is dropped if one of them failed.
   */
  readonly follows: boolean;
  /** Failed saves of its tour when it started (see `follows`). */
  readonly failuresAtStart: number;
  /** The page left this context: the save still goes out, without undo. */
  released: boolean;
  /**
   * Dropped (reset, undo, or done): a queued save no longer goes out and a
   * running one shows no toast.
   */
  cancelled: boolean;
  /** Cancelled by an undo (not by a reset): see the save's failure path. */
  superseded: boolean;
}

/**
 * Save on drop (spec D16): every move shows at once, then saves after a
 * short pause with the revision the move started from, in the context it
 * was made in. Saves of one tour run one after the other. A success shows
 * a toast with "Rückgängig"; a failure drops the local order, so the
 * server's shows again. Before the page switches day or action it calls
 * `releaseAll`: a waiting move goes out at once for its own context and no
 * longer shows.
 *
 * `key` names one tour (action, day and lane): a burst, its chain of saves
 * and its local order belong to that tour only.
 */
export function useOrderAutosave<T, C>(options: OrderAutosaveOptions<T, C>) {
  const toast = useOptionalToast();
  const latest = useRef({ options, toast });
  latest.current = { options, toast };
  const [orders, setOrders] = useState<Readonly<Record<string, string[]>>>({});
  // Created once: everything it reads lives in refs or is a state setter.
  const [saver] = useState(() => {
    const bursts = new Map<string, Burst<C>>();
    const chains = new Map<string, Promise<void>>();
    /** What the last own save of each tour returned, and when. */
    const lastSaved = new Map<
      string,
      {
        readonly revision: string;
        readonly order: readonly string[];
        readonly at: number;
      }
    >();
    /** Saves of each tour queued or running. */
    const pending = new Map<string, number>();
    /** Failed saves of each tour (shown with onFailed). */
    const failures = new Map<string, number>();
    const count = (map: Map<string, number>, key: string, by: number) =>
      map.set(key, (map.get(key) ?? 0) + by);

    const hide = (key: string) =>
      setOrders((current) => {
        if (!(key in current)) return current;
        const next = { ...current };
        delete next[key];
        return next;
      });

    /** Drops the burst of `key` if it is still this one. */
    const forget = (key: string, burst: Burst<C>) => {
      if (burst.timer) window.clearTimeout(burst.timer);
      burst.timer = null;
      burst.cancelled = true;
      if (bursts.get(key) !== burst) return;
      bursts.delete(key);
      hide(key);
    };

    const send = async (key: string, burst: Burst<C>) => {
      if (burst.cancelled || burst.sentSeq === burst.seq) return;
      const { context, ids, seq } = burst;
      const { options } = latest.current;
      // Runs after every earlier save of its tour, so it sends the revision
      // the last of them returned (a newer move may have saved after the
      // toast showed).
      if (burst.follows && burst.sentSeq === 0) {
        // A save it followed failed: the tour reloads with the server's
        // order, and this one would only fail again.
        if ((failures.get(key) ?? 0) !== burst.failuresAtStart) {
          forget(key, burst);
          return;
        }
        burst.revision = lastSaved.get(key)?.revision ?? burst.revision;
      }
      try {
        const saved = await options.save(key, ids, burst.revision, context);
        burst.revision = options.revisionOf(saved);
        burst.confirmed = ids;
        lastSaved.set(key, {
          at: Date.now(),
          order: ids,
          revision: burst.revision,
        });
        burst.sentSeq = seq;
        options.onSaved(key, saved, context);
        // Dropped meanwhile, or a newer move waits for its own save: this
        // one stays silent.
        if (burst.cancelled || burst.seq !== seq) return;
        // This save carried every move of the burst; a pause still running
        // (a move joined while the save waited in the chain) has nothing
        // left to send.
        forget(key, burst);
        const revision = burst.revision;
        latest.current.toast?.show({
          title: burst.undo
            ? options.undoneText(key, context)
            : options.savedText(key, context),
          tone: "success",
          timeout: ORDER_UNDO_MS,
          action:
            burst.undo || burst.released
              ? undefined
              : {
                  label: "Rückgängig",
                  // The toast's own tour and context, whatever shows now.
                  run: () => undo(key, burst.baseline, ids, revision, context),
                },
        });
      } catch (error) {
        // An undo took over while this save ran without an answer: the
        // order may be at Core, so it goes to the queue first (silently),
        // and the undo's order follows it there.
        if (burst.cancelled && !burst.superseded) return;
        const divertedSeq = burst.seq;
        const kept = await (
          options.divert?.(key, error, {
            baseline: burst.baseline,
            confirmed: burst.confirmed,
            context,
            ids: burst.superseded ? ids : burst.ids,
            revision: burst.revision,
            silent: burst.cancelled,
            undo: burst.undo,
          }) ?? Promise.resolve(false)
        ).catch(() => false);
        if (burst.cancelled) return;
        if (kept) {
          // The queue has it; a move made meanwhile follows on its timer.
          burst.sentSeq = divertedSeq;
          if (burst.seq === divertedSeq) forget(key, burst);
          return;
        }
        count(failures, key, 1);
        forget(key, burst);
        options.onFailed(key, error, context);
      }
    };

    const queue = (key: string, burst: Burst<C>) => {
      if (burst.timer) window.clearTimeout(burst.timer);
      burst.timer = null;
      count(pending, key, 1);
      const chain = (chains.get(key) ?? Promise.resolve())
        .then(() => send(key, burst))
        .finally(() => count(pending, key, -1));
      chains.set(key, chain);
      return chain;
    };

    function flush(key: string) {
      const burst = bursts.get(key);
      if (burst) void queue(key, burst);
    }

    const start = (
      key: string,
      current: readonly string[],
      revision: string,
      context: C,
      undo: boolean,
      follows: boolean,
    ) => {
      const burst: Burst<C> = {
        baseline: current,
        context,
        revision,
        ids: current,
        confirmed: current,
        seq: 0,
        sentSeq: 0,
        timer: null,
        undo,
        follows,
        failuresAtStart: failures.get(key) ?? 0,
        released: false,
        cancelled: false,
        superseded: false,
      };
      bursts.set(key, burst);
      return burst;
    };

    const show = (key: string, next: readonly string[]) =>
      setOrders((orders) => ({ ...orders, [key]: [...next] }));

    function move(
      key: string,
      next: readonly string[],
      current: readonly string[],
      revision: string,
      context: C,
    ) {
      const waiting = bursts.get(key);
      // A move never joins an undo: it becomes its own burst behind it,
      // with its own toast and "Rückgängig". Behind any save of the tour
      // still running (also a released one) it takes that save's revision.
      const burst =
        waiting && !waiting.undo
          ? waiting
          : start(
              key,
              current,
              revision,
              context,
              false,
              Boolean(waiting) || (pending.get(key) ?? 0) > 0,
            );
      burst.ids = next;
      burst.seq += 1;
      if (burst.timer) window.clearTimeout(burst.timer);
      const delay = latest.current.options.delayMs ?? ORDER_SAVE_DELAY_MS;
      burst.timer = window.setTimeout(() => void queue(key, burst), delay);
      show(key, next);
    }

    /**
     * "Rückgängig" on a saved toast: `baseline` goes out at once for the
     * toast's tour and context. A newer move of that tour gives way: a
     * running one finishes first, a waiting one is dropped and its order
     * leaves the screen (the user sees the order from before the toast's
     * move again).
     */
    function undo(
      key: string,
      baseline: readonly string[],
      saved: readonly string[],
      revision: string,
      context: C,
    ) {
      const newer = bursts.get(key);
      if (newer) {
        newer.superseded = true;
        forget(key, newer);
      }
      const burst = start(key, saved, revision, context, true, true);
      burst.ids = baseline;
      burst.seq = 1;
      show(key, baseline);
      void queue(key, burst);
    }

    /**
     * Before a switch of day or action: a waiting move goes out now for
     * its own context, and the tour no longer shows it. Resolves once every
     * save of `key` is through.
     */
    function release(key: string) {
      const burst = bursts.get(key);
      if (burst) {
        burst.released = true;
        bursts.delete(key);
        hide(key);
        if (burst.timer || burst.sentSeq !== burst.seq) {
          return queue(key, burst);
        }
      }
      return chains.get(key) ?? Promise.resolve();
    }

    /**
     * Sends a waiting move of `key` now and resolves once every save of it
     * is through, with what the last own save returned (null without one).
     */
    async function settle(key: string) {
      const burst = bursts.get(key);
      if (burst?.timer) void queue(key, burst);
      await (chains.get(key) ?? Promise.resolve());
      return lastSaved.get(key) ?? null;
    }

    /** Drops a waiting move unsent; resolves once a running save is through. */
    function cancel(key: string) {
      const burst = bursts.get(key);
      if (burst) forget(key, burst);
      return chains.get(key) ?? Promise.resolve();
    }

    /**
     * Leaving the page or switching day or action: as `release` for every
     * tour, so waiting moves go out and no toast offers an undo for a tour
     * that is gone (also one that left the screen before the switch).
     */
    const releaseAll = () => {
      for (const key of [...bursts.keys()]) void release(key);
    };

    return { cancel, flush, move, release, releaseAll, settle };
  });

  useEffect(() => saver.releaseAll, [saver]);

  return {
    /** The local order of a tour while it saves, else null. */
    orderOf: (key: string): readonly string[] | null => orders[key] ?? null,
    /** A tour has a move that is not saved yet. */
    dirty: Object.keys(orders).length > 0,
    /**
     * One move: `next` shows at once; `current` is the order before it,
     * `revision` the tour revision shown and `context` where it was made.
     */
    move: (
      key: string,
      next: readonly string[],
      current: readonly string[],
      revision: string,
      context: C,
    ) => saver.move(key, next, current, revision, context),
    /** Sends a waiting move now. */
    flush: saver.flush,
    releaseAll: saver.releaseAll,
    settle: saver.settle,
    cancel: saver.cancel,
  };
}
