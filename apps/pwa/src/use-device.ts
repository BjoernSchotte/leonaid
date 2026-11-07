/*
 * Identity and device storage of the PWA in one place: the identity comes
 * from Core, or offline from the device (specs/pwa-offline-queue §8.1); the
 * device storage opens only while the flag `pwa.offline_queue` is on.
 */
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  type CurrentIdentityResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
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
  const [store, setStore] = useState<DeviceStore | null>(null);
  const startedOffline = Boolean(identity.data) && fromCache.current;

  // Online: the flag decides whether the device keeps anything.
  useEffect(() => {
    const data = identity.data;
    if (!data || fromCache.current) return;
    let cancelled = false;
    void prepareDevice(client, data)
      .then((next) => {
        if (cancelled) {
          next?.close();
          return;
        }
        setStore((previous) => {
          if (previous && previous !== next) previous.close();
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

  // The read cache follows Core while online and visible (§8.2).
  useEffect(() => {
    const data = identity.data;
    if (!store || !data || fromCache.current) return;
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
    refresh(true);
    window.addEventListener("online", onOnline);
    window.addEventListener("focus", onVisible);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("focus", onVisible);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [client, identity.data, store]);

  const active = startedOffline ? cachedStore.current : store;
  const runtime = useMemo<OfflineRuntime>(
    () => ({ enabled: Boolean(active), store: active }),
    [active],
  );
  return { identity, runtime, startedOffline };
}
