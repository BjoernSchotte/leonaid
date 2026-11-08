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
 * Whether `/app/` may start from the cache. The setting lives in the
 * service worker's Cache Storage, which every page of the origin reaches,
 * so the admin web app can switch it off too.
 */
export async function setOfflineStart(enabled: boolean): Promise<void> {
  if (typeof caches === "undefined") return;
  try {
    const settings = await caches.open(SETTINGS_CACHE);
    if (enabled) {
      await settings.put(
        offlineStartKey(),
        new Response("true", { headers: { "content-type": "text/plain" } }),
      );
    } else {
      await settings.delete(offlineStartKey());
    }
  } catch {
    // Without Cache Storage there is no offline start to switch.
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
    clearActiveDeviceUser();
    await setOfflineStart(false);
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
  await setOfflineStart(false);
  if (!deviceStorageAvailable()) return;
  const users = new Set(
    [userId, activeDeviceUser()].filter((value): value is string =>
      Boolean(value),
    ),
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
