/*
 * Who owns the device copy (specs/pwa-offline-queue §8.5, D6), shared by
 * the PWA and the admin web app: they run on the same origin, so a
 * sign-out or a sign-in of another person in either app must clear what
 * the PWA kept.
 */
import { PWA_BASE } from "@leonaid/ui/base-paths";

import {
  DeviceStore,
  activeDeviceUser,
  clearActiveDeviceUser,
  deleteDeviceStore,
  deleteOtherDeviceUsers,
  deviceStorageAvailable,
} from "./device-store";

/** The service worker's cache that survives builds (see sw.js). */
export const SETTINGS_CACHE = "leonaid-pwa-settings";
/** Meta record: the session that wrote the device copy has ended (401). */
export const SESSION_ENDED_META = "sessionEnded";
export const IDENTITY_META = "identity";
const CLAIM_WAIT_MS = 3_000;

function offlineStartKey() {
  return new URL(`${PWA_BASE}offline-start`, window.location.origin).href;
}

/**
 * The setting as the pages of this origin last wrote it; `null` without
 * Cache Storage.
 */
async function storedOfflineStart(): Promise<boolean | null> {
  if (typeof caches === "undefined") return null;
  try {
    const settings = await caches.open(SETTINGS_CACHE);
    return Boolean(await settings.match(offlineStartKey()));
  } catch {
    return null;
  }
}

/**
 * Whether `/app/` may start from the cache. The setting lives in the
 * service worker's Cache Storage, which every page of the origin reaches,
 * so the admin web app can switch it off too. Switching it off also drops
 * the offline page's audience (`setOfflineAudience`).
 */
export async function setOfflineStart(enabled: boolean): Promise<void> {
  // The service worker writes its own setting (WebKit does not always
  // share a page's Cache Storage write with it); the registration is found
  // by the PWA's scope, also from an admin page it does not control.
  if ("serviceWorker" in navigator) {
    try {
      const registration =
        await navigator.serviceWorker.getRegistration(PWA_BASE);
      registration?.active?.postMessage({ type: "OFFLINE_START", enabled });
      // On the first visit the worker is still installing: it gets the
      // setting once active, or the app would start offline only after a
      // second online start (WebKit). It gets the setting as it is then,
      // not this call's value: another tab may have signed out meanwhile.
      const pending = registration?.installing ?? registration?.waiting;
      pending?.addEventListener("statechange", function onActivated() {
        if (pending.state !== "activated") return;
        pending.removeEventListener("statechange", onActivated);
        void storedOfflineStart().then((current) =>
          pending.postMessage({
            type: "OFFLINE_START",
            enabled: current ?? enabled,
          }),
        );
      });
    } catch {
      // No service worker: nothing starts offline anyway.
    }
  }
  if (typeof caches === "undefined") return;
  try {
    const settings = await caches.open(SETTINGS_CACHE);
    if (enabled) {
      await settings.put(
        offlineStartKey(),
        new Response("true", { headers: { "content-type": "text/plain" } }),
      );
    } else {
      // Off: the offline page no longer names who works offline here.
      await settings.delete(offlineStartKey());
      await settings.delete(offlineAudienceKey());
    }
  } catch {
    // Without Cache Storage there is no offline start to switch.
  }
}

/** Who the offline page (offline.html) speaks to; no personal data. */
export type OfflineAudience = "acquirer" | "driver" | "both";

function offlineAudienceKey() {
  return new URL(`${PWA_BASE}offline-audience`, window.location.origin).href;
}

/**
 * What the offline page names as still working offline: the sponsors, the
 * driver's tour (krapfentaxi-touren §9) or both. Read by offline.js from
 * the origin's Cache Storage.
 */
export async function setOfflineAudience(
  audience: OfflineAudience,
): Promise<void> {
  if (typeof caches === "undefined") return;
  try {
    const settings = await caches.open(SETTINGS_CACHE);
    await settings.put(
      offlineAudienceKey(),
      new Response(audience, { headers: { "content-type": "text/plain" } }),
    );
  } catch {
    // Without Cache Storage the page keeps its default copy.
  }
}

/**
 * D6, before the signed-in user's work renders, in either app: every other
 * person's database on this device is deleted without asking, and the
 * offline start is off until this user's own copy exists.
 */
export async function claimDevice(userId: string): Promise<void> {
  if (!deviceStorageAvailable()) return;
  const active = activeDeviceUser();
  if (active && active.toLowerCase() !== userId.toLowerCase()) {
    // Off first: the offline start is on only while a device user is
    // recorded (see forgetDevice).
    await setOfflineStart(false);
    clearActiveDeviceUser();
  }
  // The deletion waits while an open tab of the other person still holds
  // the database. No page opens another user's database, so after a short
  // wait the work renders and the deletion finishes when that tab lets go.
  await Promise.race([
    deleteOtherDeviceUsers(userId),
    new Promise((resolve) => setTimeout(resolve, CLAIM_WAIT_MS)),
  ]);
}

/** Sign-out (either app) or flag off: the database and the records. */
export async function forgetDevice(userId: string | null): Promise<void> {
  const active = activeDeviceUser();
  // The offline start is switched on only after the device user is
  // recorded, and off before that record goes: without one there is
  // nothing to switch off. The PWA forgets on every online start with the
  // flag off; a Cache API call still running when the page navigates away
  // makes WebKit log "Cache API operation failed: Context is stopped".
  if (active) await setOfflineStart(false);
  if (!deviceStorageAvailable()) return;
  const users = new Set(
    [userId, active].filter((value): value is string => Boolean(value)),
  );
  clearActiveDeviceUser();
  await Promise.all([...users].map((user) => deleteDeviceStore(user)));
}

/**
 * The session ended (401): the read cache and the identity go, so the app
 * does not start offline as this user; queued entries stay for the same
 * user's next sign-in (§8.5).
 */
export async function forgetSession(store?: DeviceStore | null): Promise<void> {
  const userId = activeDeviceUser();
  if (!userId || !deviceStorageAvailable()) return;
  const own = store?.open && store.userId === userId ? store : null;
  const target = own ?? (await DeviceStore.open(userId));
  try {
    await target.clearCache();
    await target.deleteMeta(IDENTITY_META);
    await target.putMeta(SESSION_ENDED_META, true);
  } finally {
    if (!own) target.close();
  }
  await setOfflineStart(false);
}
