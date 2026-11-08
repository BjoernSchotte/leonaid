/*
 * The PWA's side of the device storage (specs/pwa-offline-queue §8): which
 * user owns the device, the identity for an offline start, the read-cache
 * refresh and the clearing rules of §8.5. Everything here is behind the
 * flag `pwa.offline_queue`; with it off nothing is kept on the device.
 */
import type {
  AcquisitionActivityBoardResponse,
  CommitmentCaptureContextResponse,
  CurrentIdentityResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import {
  DeviceStore,
  activeDeviceUser,
  cacheFreshness,
  clearActiveDeviceUser,
  deleteDeviceStore,
  deleteOtherDeviceUsers,
  deviceStorageAvailable,
  identityFromSummary,
  minimizeBoard,
  minimizeCaptureContext,
  sessionEnded,
  setActiveDeviceUser,
  summarizeIdentity,
  type IdentitySummary,
} from "@leonaid/features/offline";

export const OFFLINE_QUEUE_FLAG = "pwa.offline_queue";
const IDENTITY_META = "identity";
const ENABLED_META = "offlineEnabled";
const CLAIM_WAIT_MS = 3_000;

/** Tells the service worker whether `/app/` may start from the cache. */
export function tellServiceWorker(enabled: boolean) {
  if (!("serviceWorker" in navigator)) return;
  void navigator.serviceWorker.ready
    .then((registration) =>
      registration.active?.postMessage({ type: "OFFLINE_START", enabled }),
    )
    .catch(() => undefined);
}

/**
 * D6, before the signed-in user's shell renders: every other person's
 * database on this device is deleted without asking.
 */
export async function claimDevice(userId: string): Promise<void> {
  if (!deviceStorageAvailable()) return;
  const active = activeDeviceUser();
  // The deletion waits while another open tab of the other person still
  // holds the database. The shell never opens another user's database, so
  // after a short wait it renders and the deletion finishes in the
  // background as soon as that tab lets go.
  await Promise.race([
    deleteOtherDeviceUsers(userId),
    new Promise((resolve) => setTimeout(resolve, CLAIM_WAIT_MS)),
  ]);
  if (active && active.toLowerCase() !== userId.toLowerCase()) {
    clearActiveDeviceUser();
  }
}

/** Offline start (§8.1): the last identity of the device's user, if any. */
export async function cachedDevice(): Promise<{
  readonly identity: CurrentIdentityResponse;
  readonly store: DeviceStore;
} | null> {
  const userId = activeDeviceUser();
  if (!userId || !deviceStorageAvailable()) return null;
  const store = await DeviceStore.open(userId);
  try {
    const enabled = await store.getMeta<boolean>(ENABLED_META);
    const summary = await store.getMeta<IdentitySummary>(IDENTITY_META);
    if (
      enabled !== true ||
      !summary ||
      summary.userId.toLowerCase() !== userId.toLowerCase()
    ) {
      store.close();
      return null;
    }
    if (sessionEnded(summary)) {
      // The session ended: the read cache goes, the queue stays (§8.5).
      await store.clearCache();
      store.close();
      return null;
    }
    return { identity: identityFromSummary(summary), store };
  } catch (error) {
    store.close();
    throw error;
  }
}

async function offlineQueueEnabled(client: LeonAidApiClient) {
  const evaluation = await client.getFeatureFlagEvaluations({ surface: "pwa" });
  return evaluation.flags.some(
    (flag) => flag.key === OFFLINE_QUEUE_FLAG && flag.enabled,
  );
}

/**
 * The device after an online start: `on` keeps the read cache and queues
 * captures; `drain` (flag switched off, or no acquirer role any more, with
 * entries still on the device) only sends what is queued and then clears
 * the device; null keeps nothing.
 */
export interface PreparedDevice {
  readonly store: DeviceStore;
  readonly mode: "on" | "drain";
}

/**
 * Online start: with the flag on and an acquirer role, the user's device
 * storage is opened and the identity summary written; otherwise nothing of
 * this user stays on the device, except queued entries until they are sent.
 * Undefined without a decision (the flag could not be read), which keeps
 * the device as it is.
 */
export async function prepareDevice(
  client: LeonAidApiClient,
  identity: CurrentIdentityResponse,
): Promise<PreparedDevice | null | undefined> {
  if (!deviceStorageAvailable()) return null;
  let enabled: boolean;
  try {
    enabled = await offlineQueueEnabled(client);
  } catch {
    return undefined;
  }
  const acquirer = identity.actionMemberships.some(
    (membership) => membership.role === "acquirer",
  );
  if (!enabled || !acquirer) {
    const store = await openIfQueued(identity.userId);
    if (store) {
      // Captures already saved are still sent; nothing new is kept.
      tellServiceWorker(false);
      await store.clearCache();
      return { mode: "drain", store };
    }
    await forgetDevice(identity.userId);
    return null;
  }
  setActiveDeviceUser(identity.userId);
  const store = await DeviceStore.open(identity.userId);
  await store.putMeta(IDENTITY_META, summarizeIdentity(identity));
  await store.putMeta(ENABLED_META, true);
  tellServiceWorker(true);
  return { mode: "on", store };
}

/** The user's database, only when it holds queued entries. */
async function openIfQueued(userId: string): Promise<DeviceStore | null> {
  if (activeDeviceUser()?.toLowerCase() !== userId.toLowerCase()) return null;
  const store = await DeviceStore.open(userId);
  if ((await store.queueCount()) > 0) {
    await store.putMeta(ENABLED_META, false);
    return store;
  }
  store.close();
  return null;
}

/**
 * Replaces the read cache per acquirer action (§8.2) and drops what the
 * acquirer may no longer see: actions without an acquirer role and
 * documents past 14 days.
 */
/** How the refresh loads Core's data; the PWA shares its page queries. */
export interface ReadCacheLoaders {
  readonly board: (
    actionId: string,
  ) => Promise<AcquisitionActivityBoardResponse>;
  readonly capture: (
    actionId: string,
  ) => Promise<CommitmentCaptureContextResponse>;
}

export async function refreshReadCache(
  loaders: ReadCacheLoaders,
  store: DeviceStore,
  identity: CurrentIdentityResponse,
): Promise<void> {
  const actions = new Set(
    identity.actionMemberships
      .filter((membership) => membership.role === "acquirer")
      .map((membership) => membership.actionId),
  );
  for (const entry of await store.listCache()) {
    if (
      !actions.has(entry.actionId) ||
      cacheFreshness(entry.fetchedAt) === "expired"
    ) {
      await store.deleteCache(entry.kind, entry.actionId);
    }
  }
  for (const actionId of actions) {
    const fetchedAt = new Date().toISOString();
    const [board, context] = await Promise.allSettled([
      loaders.board(actionId),
      loaders.capture(actionId),
    ]);
    if (board.status === "fulfilled") {
      await store.putCache(
        "board",
        actionId,
        minimizeBoard(board.value),
        fetchedAt,
      );
    }
    if (context.status === "fulfilled") {
      await store.putCache(
        "capture",
        actionId,
        minimizeCaptureContext(context.value),
        fetchedAt,
      );
    }
  }
}

/** Session ended (401): the read cache goes, the queue stays (§8.5). */
export async function forgetReadCache(): Promise<void> {
  const userId = activeDeviceUser();
  if (!userId || !deviceStorageAvailable()) return;
  const store = await DeviceStore.open(userId);
  try {
    await store.clearCache();
  } finally {
    store.close();
  }
}

/** Sign-out or flag off: the user's database and the active-user record. */
export async function forgetDevice(userId: string | null): Promise<void> {
  tellServiceWorker(false);
  if (!deviceStorageAvailable()) return;
  const users = new Set(
    [userId, activeDeviceUser()].filter((value): value is string =>
      Boolean(value),
    ),
  );
  clearActiveDeviceUser();
  await Promise.all([...users].map((user) => deleteDeviceStore(user)));
}
