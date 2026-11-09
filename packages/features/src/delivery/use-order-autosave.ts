import { useEffect, useRef, useState } from "react";

import { useOptionalToast } from "@leonaid/ui";

/** Chained moves within this time go out as one save (spec D16). */
export const ORDER_SAVE_DELAY_MS = 600;
/** How long "Rückgängig" stays on the saved toast. */
export const ORDER_UNDO_MS = 10_000;

export interface OrderAutosaveOptions<T> {
  /** Sends one order of the tour `key` with the revision the user saw. */
  readonly save: (
    key: string,
    ids: readonly string[],
    revision: string,
  ) => Promise<T>;
  readonly revisionOf: (saved: T) => string;
  /** The saved tour, to put into the query cache. */
  readonly onSaved: (key: string, saved: T) => void;
  /**
   * A failed save. The shown order is already back at the server's; say
   * why and reload when the tour changed meanwhile.
   */
  readonly onFailed: (key: string, error: unknown) => void;
  readonly savedText: (key: string) => string;
  readonly undoneText: (key: string) => string;
  readonly delayMs?: number;
}

interface Burst {
  /** The order before the first move; "Rückgängig" restores it. */
  readonly baseline: readonly string[];
  /** The revision the next save sends; moves on with each own save. */
  revision: string;
  ids: readonly string[];
  /** Bumped by each move; a save only settles the burst if none followed. */
  seq: number;
  sentSeq: number;
  timer: number | null;
  /** This burst is an undo: its toast has no "Rückgängig". */
  readonly undo: boolean;
}

/**
 * Save on drop (spec D16): every move shows at once, then saves after a
 * short pause with the revision the move started from. Saves of one tour
 * run one after the other. A success shows a toast with "Rückgängig"; a
 * failure drops the local order, so the server's shows again.
 */
export function useOrderAutosave<T>(options: OrderAutosaveOptions<T>) {
  const toast = useOptionalToast();
  const latest = useRef({ options, toast });
  latest.current = { options, toast };
  const [orders, setOrders] = useState<Readonly<Record<string, string[]>>>({});
  // Created once: everything it reads lives in refs or is a state setter.
  const [saver] = useState(() => {
    const bursts = new Map<string, Burst>();
    const chains = new Map<string, Promise<void>>();

    const forget = (key: string) => {
      const burst = bursts.get(key);
      if (burst?.timer) window.clearTimeout(burst.timer);
      bursts.delete(key);
      setOrders((current) => {
        if (!(key in current)) return current;
        const next = { ...current };
        delete next[key];
        return next;
      });
    };

    const send = async (key: string) => {
      const burst = bursts.get(key);
      if (!burst || burst.sentSeq === burst.seq) return;
      const { ids, seq } = burst;
      const { options } = latest.current;
      try {
        const saved = await options.save(key, ids, burst.revision);
        burst.revision = options.revisionOf(saved);
        burst.sentSeq = seq;
        options.onSaved(key, saved);
        // A newer move waits for its own save; this one stays silent.
        if (bursts.get(key) !== burst || burst.seq !== seq || burst.timer) {
          return;
        }
        forget(key);
        const revision = burst.revision;
        latest.current.toast?.show({
          title: burst.undo ? options.undoneText(key) : options.savedText(key),
          tone: "success",
          timeout: ORDER_UNDO_MS,
          action: burst.undo
            ? undefined
            : {
                label: "Rückgängig",
                run: () => {
                  move(key, burst.baseline, ids, revision, true);
                  flush(key);
                },
              },
        });
      } catch (error) {
        if (bursts.get(key) === burst) forget(key);
        options.onFailed(key, error);
      }
    };

    function flush(key: string) {
      const burst = bursts.get(key);
      if (!burst) return;
      if (burst.timer) window.clearTimeout(burst.timer);
      burst.timer = null;
      const chain = (chains.get(key) ?? Promise.resolve()).then(() =>
        send(key),
      );
      chains.set(key, chain);
    }

    function move(
      key: string,
      next: readonly string[],
      current: readonly string[],
      revision: string,
      undo = false,
    ) {
      let burst = bursts.get(key);
      if (!burst || undo) {
        if (burst?.timer) window.clearTimeout(burst.timer);
        burst = {
          baseline: current,
          revision: burst?.revision ?? revision,
          ids: current,
          seq: 0,
          sentSeq: 0,
          timer: null,
          undo,
        };
        bursts.set(key, burst);
      }
      burst.ids = next;
      burst.seq += 1;
      if (burst.timer) window.clearTimeout(burst.timer);
      const delay = latest.current.options.delayMs ?? ORDER_SAVE_DELAY_MS;
      burst.timer = window.setTimeout(() => flush(key), delay);
      setOrders((orders) => ({ ...orders, [key]: [...next] }));
    }

    /** Sends every waiting move now (leaving the page). */
    const flushAll = () => {
      for (const [key, burst] of bursts) if (burst.timer) flush(key);
    };

    return { flush, flushAll, move };
  });

  useEffect(() => saver.flushAll, [saver]);

  return {
    /** The local order of a tour while it saves, else null. */
    orderOf: (key: string): readonly string[] | null => orders[key] ?? null,
    /** A tour has a move that is not saved yet. */
    dirty: Object.keys(orders).length > 0,
    /**
     * One move: `next` shows at once; `current` is the order before it and
     * `revision` the tour revision shown.
     */
    move: (
      key: string,
      next: readonly string[],
      current: readonly string[],
      revision: string,
    ) => saver.move(key, next, current, revision),
    /** Sends a waiting move now. */
    flush: saver.flush,
  };
}
