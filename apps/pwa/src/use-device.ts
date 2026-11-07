/*
 * Identity, device storage and capture queue of the PWA in one place: the
 * identity comes from Core, or offline from the device (specs/pwa-offline-
 * queue §8.1); the device storage and the queue open only while the flag
 * `pwa.offline_queue` is on, or while queued entries still wait to be sent.
 */
import {
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  type CurrentIdentityResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  DeviceQueueStore,
  QueueController,
  isNetworkFailure,
  sendEntry,
  type DeviceStore,
  type OfflineRuntime,
} from "@leonaid/features/offline";

import {
  cachedDevice,
  claimDevice,
  forgetDevice,
  prepareDevice,
  refreshReadCache,
  type PreparedDevice,
} from "./device";

/** The read cache refreshes at most this often on focus (§8.2). */
const REFRESH_INTERVAL_MS = 60_000;

export interface DeviceState {
  readonly identity: UseQueryResult<CurrentIdentityResponse>;
  /** The identity came from the device: Core was not reachable. */
  readonly startedOffline: boolean;
  readonly runtime: OfflineRuntime;
}

export function useDevice(
  client: LeonAidApiClient,
  online: boolean,
): DeviceState {
  const queries = useQueryClient();
  const cachedStore = useRef<DeviceStore | null>(null);
  const fromCache = useRef(false);
  const identity = useQuery({
    queryFn: async () => {
      try {
        const value = await client.getCurrentIdentity();
        fromCache.current = false;
        // D6: nothing of another person survives into this shell.
        await claimDevice(value.userId).catch(() => undefined);
        return value;
      } catch (error) {
        if (!isNetworkFailure(error)) throw error;
        const device = await cachedDevice().catch(() => null);
        if (!device) throw error;
        if (cachedStore.current !== device.store) cachedStore.current?.close();
        cachedStore.current = device.store;
        fromCache.current = true;
        return device.identity;
      }
    },
    queryKey: ["identity"],
    retry: (failureCount, error) =>
      !(error instanceof ApiError) && failureCount < 2,
    retryDelay: (attempt) => 150 * (attempt + 1),
    staleTime: 30_000,
  });
  // undefined until the online start decided; null keeps nothing.
  const [prepared, setPrepared] = useState<PreparedDevice | null>();
  const startedOffline = Boolean(identity.data) && fromCache.current;

  // Online: the flag decides whether the device keeps anything.
  useEffect(() => {
    const data = identity.data;
    if (!data || fromCache.current) return;
    let cancelled = false;
    void prepareDevice(client, data)
      .then((next) => {
        if (next === undefined) return;
        if (cancelled) {
          next?.store.close();
          return;
        }
        setPrepared((previous) => {
          if (previous && previous.store !== next?.store) {
            previous.store.close();
          }
          return next;
        });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [client, identity.data]);

  // Started from the device: back online, Core answers again.
  useEffect(() => {
    if (startedOffline && online) void identity.refetch();
  }, [startedOffline, online]);

  // Back online after an offline start, the device copy stays in use
  // until the flag has been read again, so the queue never disappears.
  const undecided = startedOffline || prepared === undefined;
  const store = undecided ? cachedStore.current : (prepared?.store ?? null);
  const mode = undecided
    ? cachedStore.current
      ? "on"
      : null
    : (prepared?.mode ?? null);
  const userId = identity.data?.userId ?? "";

  // The read cache follows Core while online and visible (§8.2).
  useEffect(() => {
    const data = identity.data;
    if (!store || mode !== "on" || !data || fromCache.current) return;
    let last = 0;
    let running = false;
    const refresh = (force: boolean) => {
      if (running || navigator.onLine === false) return;
      if (document.visibilityState !== "visible") return;
      if (!force && Date.now() - last < REFRESH_INTERVAL_MS) return;
      running = true;
      last = Date.now();
      void refreshReadCache(client, store, data)
        .catch(() => undefined)
        .finally(() => {
          running = false;
        });
    };
    const onOnline = () => refresh(true);
    const onVisible = () => refresh(false);
    const onSent = () => refresh(true);
    refresh(true);
    window.addEventListener("online", onOnline);
    window.addEventListener("focus", onVisible);
    window.addEventListener("leonaid:queue-sent", onSent);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("focus", onVisible);
      window.removeEventListener("leonaid:queue-sent", onSent);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [client, identity.data, mode, store]);

  // The capture queue (§9): one controller per open device storage.
  const [queue, setQueue] = useState<QueueController | null>(null);
  useEffect(() => {
    if (!store || !userId) return;
    const controller = new QueueController({
      onAccepted: () => {
        // §9.4: the read cache and the pages follow each accepted entry.
        void queries.invalidateQueries({
          queryKey: ["acquisition-activity-board"],
        });
        void queries.invalidateQueries({ queryKey: ["dashboard"] });
        void queries.invalidateQueries({ queryKey: ["activity-feed"] });
        window.dispatchEvent(new Event("leonaid:queue-sent"));
      },
      send: (entry) => sendEntry(client, entry),
      store: new DeviceQueueStore(store),
      userId,
    });
    const stop = controller.start();
    setQueue(controller);
    return () => {
      stop();
      setQueue(null);
    };
  }, [client, queries, store, userId]);

  // Drain mode: once everything is sent, nothing stays on the device.
  useEffect(() => {
    if (!queue || mode !== "drain") return;
    return queue.subscribe((snapshot) => {
      if (!snapshot.sending && snapshot.entries.length === 0) {
        void forgetDevice(userId).then(() => setPrepared(null));
      }
    });
  }, [mode, queue, userId]);

  const runtime = useMemo<OfflineRuntime>(
    () => ({
      enabled: mode === "on" && Boolean(store),
      queue,
      store: mode === "on" ? store : null,
    }),
    [mode, queue, store],
  );
  return { identity, runtime, startedOffline };
}
