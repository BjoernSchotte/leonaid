/*
 * Identity and device storage of the PWA in one place: the identity comes
 * from Core, or offline from the device (specs/pwa-offline-queue §8.1); the
 * device storage and the capture queue open only while the flag
 * `pwa.offline_queue` is on, or while queued entries still wait. One
 * store per page life and user: offline starts, refetches and the switch
 * back online reuse it.
 */
import {
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  type AcquisitionActivityBoardResponse,
  type CommitmentCaptureContextResponse,
  type CurrentIdentityResponse,
  type LeonAidApiClient,
  type MyTourResponse,
} from "@leonaid/api-client";
import {
  DeviceQueueStore,
  QueueController,
  SEND_TIMEOUT_MS,
  deviceCopyFetchedAt,
  forgetDevice,
  isNetworkFailure,
  preflightConflict,
  sendEntry,
  sendTourReads,
  withAcceptedWrite,
  type DeviceStore,
  type OfflineRuntime,
  type QueueSnapshot,
} from "@leonaid/features/offline";

import {
  cachedDevice,
  claimDevice,
  prepareDevice,
  refreshReadCache,
  type DeviceFlags,
  type PreparedDevice,
} from "./device";

/** The read cache refreshes at most this often on focus (§8.2). */
const REFRESH_INTERVAL_MS = 60_000;
/** The pages load the same data at start; the refresh reuses it. */
const START_REFRESH_DELAY_MS = 2_000;
/** A page answer younger than this is reused instead of asking again. */
const REUSE_MS = 15_000;

export interface DeviceState {
  readonly identity: UseQueryResult<CurrentIdentityResponse>;
  /** The identity came from the device: Core was not reachable. */
  readonly startedOffline: boolean;
  readonly runtime: OfflineRuntime;
  /**
   * The flags of the device's last online start; the shell settles on them
   * while Core is out of reach. Null without device storage.
   */
  readonly cachedFlags: DeviceFlags | null;
}

export function useDevice(
  client: LeonAidApiClient,
  online: boolean,
): DeviceState {
  const queries = useQueryClient();
  // The one open store of this page; offline start and online preparation
  // hand it to each other instead of opening new connections.
  const openStore = useRef<DeviceStore | null>(null);
  const fromCache = useRef(false);
  const deviceFlags = useRef<DeviceFlags | null>(null);
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
        // A session that ended is an ApiError 401 here: go to sign-in.
        const device = await cachedDevice(openStore.current).catch(
          (failure: unknown) => {
            if (failure instanceof ApiError) throw failure;
            return null;
          },
        );
        if (!device) throw error;
        openStore.current = device.store;
        deviceFlags.current = device.flags;
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
  const userId = identity.data?.userId ?? "";
  const acquirerActions = (identity.data?.actionMemberships ?? [])
    .filter((membership) => membership.role === "acquirer")
    .map((membership) => membership.actionId)
    .sort()
    .join(",");
  // A driver's tour copy follows the actions they drive for (D14 g).
  const driverActions = (identity.data?.actionMemberships ?? [])
    .filter((membership) => membership.role === "driver")
    .map((membership) => membership.actionId)
    .sort()
    .join(",");
  const latestIdentity = useRef(identity.data);
  latestIdentity.current = identity.data;

  // Online: the flag decides whether the device keeps anything. Runs per
  // user and campaign set, not on every identity refetch.
  useEffect(() => {
    const data = latestIdentity.current;
    if (!data || fromCache.current) return;
    let cancelled = false;
    void prepareDevice(client, data, openStore.current)
      .then((next) => {
        if (next === undefined || cancelled) return;
        if (openStore.current && openStore.current !== next?.store) {
          openStore.current.close();
        }
        openStore.current = next?.store ?? null;
        deviceFlags.current = next?.mode === "on" ? next.flags : null;
        setPrepared(next);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [client, userId, acquirerActions, driverActions, startedOffline]);

  // Started from the device: back online, Core answers again.
  useEffect(() => {
    if (startedOffline && online) void identity.refetch();
  }, [startedOffline, online]);

  // Until the online start decided, an offline-started store stays in use.
  const undecided = startedOffline || prepared === undefined;
  const store = undecided ? openStore.current : (prepared?.store ?? null);
  const mode = undecided
    ? openStore.current
      ? "on"
      : null
    : (prepared?.mode ?? null);

  // The read cache follows Core while online and visible (§8.2).
  useEffect(() => {
    if (!store || mode !== "on" || startedOffline || !userId) return;
    let last = 0;
    let running = false;
    // A page that just loaded the same data from Core lends it: the board
    // reads the CRM, which is rate-limited. A device copy shown offline is
    // never written back as fresh.
    function recent<T>(key: readonly unknown[]): T | null {
      const state = queries.getQueryState(key);
      const value = queries.getQueryData<T>(key);
      if (!state || value === undefined) return null;
      if (Date.now() - state.dataUpdatedAt > REUSE_MS) return null;
      return deviceCopyFetchedAt(value) ? null : value;
    }
    const loaders = {
      board: async (actionId: string) =>
        recent<AcquisitionActivityBoardResponse>([
          "acquisition-activity-board",
          actionId,
        ]) ?? client.getAcquisitionActivityBoard(actionId, { limit: 100 }),
      capture: async (actionId: string) =>
        recent<CommitmentCaptureContextResponse>([
          "commitment-capture-context",
          actionId,
        ]) ?? client.getCommitmentCaptureContext(actionId),
    };
    const refresh = (force: boolean) => {
      const data = latestIdentity.current;
      if (!data || running || navigator.onLine === false) return;
      if (document.visibilityState !== "visible") return;
      if (!force && Date.now() - last < REFRESH_INTERVAL_MS) return;
      running = true;
      last = Date.now();
      void refreshReadCache(loaders, store, data)
        .catch(() => undefined)
        .finally(() => {
          running = false;
        });
    };
    const onOnline = () => refresh(true);
    const onVisible = () => refresh(false);
    // Pages showing the board refetch it after a send (and update the copy
    // through readThrough); the full refresh keeps its pace, so a burst of
    // sends does not hammer Core and the CRM behind it.
    const onSent = () => refresh(false);
    const first = setTimeout(() => refresh(true), START_REFRESH_DELAY_MS);
    window.addEventListener("online", onOnline);
    window.addEventListener("focus", onVisible);
    window.addEventListener("leonaid:queue-sent", onSent);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearTimeout(first);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("focus", onVisible);
      window.removeEventListener("leonaid:queue-sent", onSent);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [client, queries, mode, startedOffline, store, userId, acquirerActions]);

  // The capture queue (§9): one controller per open device storage.
  const [queue, setQueue] = useState<QueueController | null>(null);
  useEffect(() => {
    if (!store || !userId) return;
    const controller = new QueueController({
      onAccepted: (report) => {
        // "Meine Tour" shows Core's answer at once; the page reloads the
        // tour itself once its entries left the queue (§9).
        for (const { entry, result } of report.accepted) {
          if (
            result.kind !== "delivery-state" &&
            result.kind !== "tour-order"
          ) {
            continue;
          }
          queries.setQueriesData<MyTourResponse>(
            { queryKey: ["my-tour", entry.actionId] },
            (current) =>
              current ? withAcceptedWrite(current, result) : current,
          );
        }
        // §9.4: the read cache and the pages follow each accepted entry.
        void queries.invalidateQueries({
          queryKey: ["acquisition-activity-board"],
        });
        void queries.invalidateQueries({ queryKey: ["dashboard"] });
        void queries.invalidateQueries({ queryKey: ["activity-feed"] });
        window.dispatchEvent(new Event("leonaid:queue-sent"));
      },
      preflight: async (entry) => {
        if (entry.kind !== "commitment") return null;
        const cached = await store
          .getCache<CommitmentCaptureContextResponse>("capture", entry.actionId)
          .catch(() => undefined);
        return preflightConflict(entry, cached?.value);
      },
      send: (entry) => sendEntry(client, entry),
      // The driver's offline reads of "Meine Tour" (spec §10).
      sendRecords: () =>
        sendTourReads(store, (actionId, body) =>
          client.recordMyTourReads(actionId, body, {
            signal: AbortSignal.timeout(SEND_TIMEOUT_MS),
          }),
        ),
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
    let done = false;
    const clearIfEmpty = (snapshot: QueueSnapshot) => {
      if (done || snapshot.sending || snapshot.entries.length > 0) return;
      done = true;
      void forgetDevice(userId).then(() => {
        openStore.current = null;
        setPrepared(null);
      });
    };
    const unsubscribe = queue.subscribe(clearIfEmpty);
    // A drain that finished before this effect subscribed still clears.
    void queue.reload().then(() => clearIfEmpty(queue.snapshot));
    return () => {
      done = true;
      unsubscribe();
    };
  }, [mode, queue, userId]);

  const runtime = useMemo<OfflineRuntime>(
    () => ({
      enabled: mode === "on" && Boolean(store),
      queue,
      store: mode === "on" ? store : null,
    }),
    [mode, queue, store],
  );
  return {
    cachedFlags: runtime.enabled ? deviceFlags.current : null,
    identity,
    runtime,
    startedOffline,
  };
}
