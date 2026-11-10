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
  ids: readonly string[];
  /** Bumped by each move; a save only settles the burst if none followed. */
  seq: number;
  sentSeq: number;
  timer: number | null;
  /** This burst is an undo: its toast has no "Rückgängig". */
  readonly undo: boolean;
  /** The page left this context: the save still goes out, without undo. */
  released: boolean;
  /**
   * Dropped (reset, undo, or done): a queued save no longer goes out and a
   * running one shows no toast.
   */
  cancelled: boolean;
}

/**
 * Save on drop (spec D16): every move shows at once, then saves after a
 * short pause with the revision the move started from, in the context it
 * was made in. Saves of one tour run one after the other. A success shows
 * a toast with "Rückgängig"; a failure drops the local order, so the
 * server's shows again. Before the page switches day or action it calls
 * `release`: a waiting move goes out at once for its own context and no
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
    /** The revision the last own save of each tour returned. */
    const revisions = new Map<string, string>();

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
      // An undo runs after every earlier save of its tour, so it sends the
      // revision the last of them returned (a newer move may have saved
      // after the toast showed).
      if (burst.undo && burst.sentSeq === 0) {
        burst.revision = revisions.get(key) ?? burst.revision;
      }
      try {
        const saved = await options.save(key, ids, burst.revision, context);
        burst.revision = options.revisionOf(saved);
        revisions.set(key, burst.revision);
        burst.sentSeq = seq;
        options.onSaved(key, saved, context);
        // Dropped meanwhile, or a newer move waits for its own save: this
        // one stays silent.
        if (burst.cancelled || burst.seq !== seq || burst.timer) return;
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
        if (burst.cancelled) return;
        forget(key, burst);
        options.onFailed(key, error, context);
      }
    };

    const queue = (key: string, burst: Burst<C>) => {
      if (burst.timer) window.clearTimeout(burst.timer);
      burst.timer = null;
      const chain = (chains.get(key) ?? Promise.resolve()).then(() =>
        send(key, burst),
      );
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
    ) => {
      const burst: Burst<C> = {
        baseline: current,
        context,
        revision,
        ids: current,
        seq: 0,
        sentSeq: 0,
        timer: null,
        undo,
        released: false,
        cancelled: false,
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
      const burst =
        bursts.get(key) ?? start(key, current, revision, context, false);
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
     * waiting one is dropped, a running one finishes first.
     */
    function undo(
      key: string,
      baseline: readonly string[],
      saved: readonly string[],
      revision: string,
      context: C,
    ) {
      const newer = bursts.get(key);
      if (newer) forget(key, newer);
      const burst = start(key, saved, revision, context, true);
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

    /** Drops a waiting move unsent; resolves once a running save is through. */
    function cancel(key: string) {
      const burst = bursts.get(key);
      if (burst) forget(key, burst);
      return chains.get(key) ?? Promise.resolve();
    }

    /** Sends every waiting move now (leaving the page). */
    const flushAll = () => {
      for (const [key, burst] of bursts)
        if (burst.timer) void queue(key, burst);
    };

    return { cancel, flush, flushAll, move, release };
  });

  useEffect(() => saver.flushAll, [saver]);

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
    release: saver.release,
    cancel: saver.cancel,
  };
}
