/*
 * What the feature pages know of the PWA's device storage. The admin web
 * app provides nothing, so its pages behave as before; the PWA provides
 * the runtime while the flag `pwa.offline_queue` is on
 * (specs/pwa-offline-queue §16).
 */
import { createContext, useContext } from "react";

import { ApiError } from "@leonaid/api-client";

import type { CacheKind, DeviceStore } from "./device-store";
import { cacheFreshness } from "./read-cache";

export interface OfflineRuntime {
  /** The flag is on and the device storage is open. */
  readonly enabled: boolean;
  readonly store: DeviceStore | null;
}

export const DISABLED_OFFLINE_RUNTIME: OfflineRuntime = {
  enabled: false,
  store: null,
};

export const OfflineRuntimeContext = createContext<OfflineRuntime>(
  DISABLED_OFFLINE_RUNTIME,
);

export function useOfflineRuntime(): OfflineRuntime {
  return useContext(OfflineRuntimeContext);
}

/** The cached document is older than 7 days: offline capture is blocked (D3). */
export class StaleReadCacheError extends Error {
  readonly fetchedAt: string;

  constructor(fetchedAt: string) {
    super("Deine Sponsorenliste ist älter als 7 Tage.");
    this.name = "StaleReadCacheError";
    this.fetchedAt = fetchedAt;
  }
}

export const STALE_READ_CACHE_TEXT =
  "Deine Sponsorenliste ist älter als 7 Tage. Geh online, um sie zu aktualisieren.";

/**
 * No answer from Core: no network, a timeout, a gateway error or a static
 * fallback instead of the API (a captive portal). Every other API error is
 * an answer and is shown as such.
 */
export function isNetworkFailure(error: unknown): boolean {
  // fetch() rejects with a TypeError without network; an aborted or timed
  // out request is a DOMException. A parse or programming error is not.
  if (error instanceof TypeError) return true;
  if (
    typeof DOMException !== "undefined" &&
    error instanceof DOMException &&
    (error.name === "AbortError" || error.name === "TimeoutError")
  ) {
    return true;
  }
  if (!(error instanceof ApiError)) return false;
  return (
    error.status === 502 ||
    error.status === 503 ||
    error.status === 504 ||
    error.detail.code === "unexpected_response_type"
  );
}

/** Values a page got from the device copy, with their fetch time. */
const deviceCopies = new WeakMap<object, string>();

/**
 * When the value came from the device copy: its fetch time; null for
 * Core's own answer.
 */
export function deviceCopyFetchedAt(value: unknown): string | null {
  return typeof value === "object" && value !== null
    ? (deviceCopies.get(value) ?? null)
    : null;
}

/**
 * Online: Core's answer, and the minimized copy goes to the device.
 * Without an answer: the device copy while it is younger than 7 days.
 */
export async function readThrough<T>(
  runtime: OfflineRuntime,
  kind: CacheKind,
  actionId: string,
  load: () => Promise<T>,
  minimize: (value: T) => T,
): Promise<T> {
  const store = runtime.enabled ? runtime.store : null;
  let failure: unknown;
  if (!store || navigator.onLine !== false) {
    try {
      const value = await load();
      if (store) {
        // A full device must not fail the page: the copy is a convenience.
        await store
          .putCache(kind, actionId, minimize(value), new Date().toISOString())
          .catch(() => undefined);
      }
      return value;
    } catch (error) {
      if (!store || !isNetworkFailure(error)) throw error;
      failure = error;
    }
  }
  const cached = await store!.getCache<T>(kind, actionId).catch(() => null);
  if (!cached) {
    throw failure ?? new TypeError("LeonAid is offline");
  }
  const freshness = cacheFreshness(cached.fetchedAt);
  if (freshness === "expired") {
    // Past 14 days the copy goes, also on a device that stays offline.
    await store!.deleteCache(kind, actionId).catch(() => undefined);
  }
  if (freshness !== "fresh") {
    throw new StaleReadCacheError(cached.fetchedAt);
  }
  if (typeof cached.value === "object" && cached.value !== null) {
    deviceCopies.set(cached.value, cached.fetchedAt);
  }
  return cached.value;
}
