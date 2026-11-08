/*
 * Identity and device storage of the PWA in one place: the identity comes
 * from Core, or offline from the device (specs/pwa-offline-queue §8.1); the
 * device storage opens only while the flag `pwa.offline_queue` is on. One
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
} from "@leonaid/api-client";
import {
  deviceCopyFetchedAt,
  isNetworkFailure,
  type DeviceStore,
  type OfflineRuntime,
} from "@leonaid/features/offline";

import {
  cachedDevice,
  claimDevice,
  prepareDevice,
  refreshReadCache,
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
  const [prepared, setPrepared] = useState<DeviceStore | null>();
  const startedOffline = Boolean(identity.data) && fromCache.current;
  const userId = identity.data?.userId ?? "";
  const acquirerActions = (identity.data?.actionMemberships ?? [])
    .filter((membership) => membership.role === "acquirer")
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
        if (openStore.current && openStore.current !== next) {
          openStore.current.close();
        }
        openStore.current = next;
        setPrepared(next);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [client, userId, acquirerActions, startedOffline]);

  // Started from the device: back online, Core answers again.
  useEffect(() => {
    if (startedOffline && online) void identity.refetch();
  }, [startedOffline, online]);

  // Until the online start decided, an offline-started store stays in use.
  const store =
    startedOffline || prepared === undefined ? openStore.current : prepared;

  // The read cache follows Core while online and visible (§8.2).
  useEffect(() => {
    if (!store || startedOffline || !userId) return;
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
    const first = setTimeout(() => refresh(true), START_REFRESH_DELAY_MS);
    window.addEventListener("online", onOnline);
    window.addEventListener("focus", onVisible);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearTimeout(first);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("focus", onVisible);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [client, queries, startedOffline, store, userId, acquirerActions]);

  const runtime = useMemo<OfflineRuntime>(
    () => ({ enabled: Boolean(store), store }),
    [store],
  );
  return { identity, runtime, startedOffline };
}
