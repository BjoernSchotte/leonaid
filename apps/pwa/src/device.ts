/*
 * The PWA's side of the device storage (specs/pwa-offline-queue §8): the
 * identity for an offline start, the online preparation, the read-cache
 * refresh and the clearing rules of §8.5. Ownership and clearing that the
 * admin web app shares live in @leonaid/features/offline (device-session).
 * Everything here is behind the flag `pwa.offline_queue`; with it off
 * nothing is kept on the device. The driver's tour needs `delivery.tours`
 * too (krapfentaxi-touren §9, D14 g).
 */
import {
  ApiError,
  type AcquisitionActivityBoardResponse,
  type CommitmentCaptureContextResponse,
  type CurrentIdentityResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  DeviceStore,
  IDENTITY_META,
  SESSION_ENDED_META,
  activeDeviceUser,
  cacheFreshness,
  deviceStorageAvailable,
  forgetDevice,
  forgetSession,
  identityFromSummary,
  minimizeBoard,
  minimizeCaptureContext,
  purgeTourCaches,
  sessionEnded,
  setActiveDeviceUser,
  setOfflineStart,
  summarizeIdentity,
  type IdentitySummary,
} from "@leonaid/features/offline";

export {
  claimDevice,
  forgetDevice,
  forgetSession,
} from "@leonaid/features/offline";

export const OFFLINE_QUEUE_FLAG = "pwa.offline_queue";
export const DELIVERY_TOURS_FLAG = "delivery.tours";
const ENABLED_META = "offlineEnabled";
/**
 * The PWA's flags at the last online start: an offline start shows the
 * same pages (no personal data, only flag keys and values).
 */
const FLAGS_META = "flags";

export type DeviceFlags = ReadonlyMap<string, boolean>;

/** Driver actions whose tour the device keeps: both flags on (D14 g). */
function tourActions(
  memberships: CurrentIdentityResponse["actionMemberships"],
  flags: DeviceFlags,
): Set<string> {
  if (
    flags.get(OFFLINE_QUEUE_FLAG) !== true ||
    flags.get(DELIVERY_TOURS_FLAG) !== true
  ) {
    return new Set();
  }
  return new Set(
    memberships
      .filter((membership) => membership.role === "driver")
      .map((membership) => membership.actionId),
  );
}

/** What an offline start returns when the session behind the copy ended. */
function sessionEndedError() {
  return new ApiError(401, {
    code: "session_required",
    message: "Deine Sitzung ist abgelaufen. Melde dich wieder an.",
    requestId: "",
  });
}

/**
 * Removes read-cache documents past 14 days (§8.5), online or not. The
 * driver's tour has its own rules (purgeTourCaches).
 */
async function purgeExpired(store: DeviceStore, keep?: ReadonlySet<string>) {
  for (const entry of await store.listCache()) {
    if (entry.kind === "tour") continue;
    if (
      (keep && !keep.has(entry.actionId)) ||
      cacheFreshness(entry.fetchedAt) === "expired"
    ) {
      await store.deleteCache(entry.kind, entry.actionId);
    }
  }
}

/**
 * Offline start (§8.1): the last identity of the device's user, if any.
 * An open store of the same user is reused. A session that ended (401 or
 * past its lifetime) does not start offline: it asks for a sign-in.
 */
export async function cachedDevice(existing?: DeviceStore | null): Promise<{
  readonly identity: CurrentIdentityResponse;
  readonly store: DeviceStore;
  readonly flags: DeviceFlags;
} | null> {
  const userId = activeDeviceUser();
  if (!userId || !deviceStorageAvailable()) return null;
  const reuse = existing?.open && existing.userId === userId ? existing : null;
  const store = reuse ?? (await DeviceStore.open(userId));
  const drop = () => {
    if (!reuse) store.close();
  };
  try {
    if ((await store.getMeta<boolean>(SESSION_ENDED_META)) === true) {
      drop();
      throw sessionEndedError();
    }
    const enabled = await store.getMeta<boolean>(ENABLED_META);
    const summary = await store.getMeta<IdentitySummary>(IDENTITY_META);
    if (
      enabled !== true ||
      !summary ||
      summary.userId.toLowerCase() !== userId.toLowerCase()
    ) {
      drop();
      return null;
    }
    if (sessionEnded(summary)) {
      await forgetSession(store);
      drop();
      throw sessionEndedError();
    }
    await purgeExpired(store);
    const flags = new Map(
      Object.entries(
        (await store.getMeta<Record<string, boolean>>(FLAGS_META)) ?? {},
      ),
    );
    await purgeTourCaches(store, tourActions(summary.memberships, flags));
    return { identity: identityFromSummary(summary), store, flags };
  } catch (error) {
    drop();
    throw error;
  }
}

async function pwaFlags(client: LeonAidApiClient): Promise<DeviceFlags> {
  const evaluation = await client.getFeatureFlagEvaluations({ surface: "pwa" });
  return new Map(evaluation.flags.map((flag) => [flag.key, flag.enabled]));
}

/**
 * The device after an online start: `on` keeps the read cache and queues
 * captures; `drain` (flag switched off, or no acquirer role any more, with
 * entries still on the device) only sends what is queued and then clears
 * the device.
 */
export interface PreparedDevice {
  readonly store: DeviceStore;
  readonly mode: "on" | "drain";
  /** The flags this start was decided on. */
  readonly flags: DeviceFlags;
}

/**
 * Online start: with the flag on and an acquirer role (or a driver role
 * with `delivery.tours` on), the user's device storage is opened (or the
 * open one reused) and the identity summary written; otherwise nothing of
 * this user stays on the device, except queued entries until they are
 * sent. Tour copies of actions the user no longer drives for, or all of
 * them with `delivery.tours` off, are deleted. Undefined without a
 * decision (the flags could not be read): the device stays as it is.
 */
export async function prepareDevice(
  client: LeonAidApiClient,
  identity: CurrentIdentityResponse,
  existing?: DeviceStore | null,
): Promise<PreparedDevice | null | undefined> {
  if (!deviceStorageAvailable()) return null;
  let flags: DeviceFlags;
  try {
    flags = await pwaFlags(client);
  } catch {
    return undefined;
  }
  const enabled = flags.get(OFFLINE_QUEUE_FLAG) === true;
  const acquirer = identity.actionMemberships.some(
    (membership) => membership.role === "acquirer",
  );
  const tours = tourActions(identity.actionMemberships, flags);
  if (!enabled || (!acquirer && !tours.size)) {
    const queued = await openIfQueued(identity.userId, existing);
    if (queued) {
      // Captures already saved are still sent; nothing new is kept.
      await setOfflineStart(false);
      await queued.clearCache();
      return { flags, mode: "drain", store: queued };
    }
    await forgetDevice(identity.userId);
    return null;
  }
  setActiveDeviceUser(identity.userId);
  const store =
    existing?.open && existing.userId === identity.userId
      ? existing
      : await DeviceStore.open(identity.userId);
  await store.putMeta(
    IDENTITY_META,
    summarizeIdentity(identity, new Date(), { drivers: tours.size > 0 }),
  );
  await store.putMeta(FLAGS_META, Object.fromEntries(flags));
  await store.putMeta(ENABLED_META, true);
  await store.deleteMeta(SESSION_ENDED_META);
  await purgeTourCaches(store, tours);
  await setOfflineStart(true);
  return { flags, mode: "on", store };
}

/** The user's database, only when it holds queued entries. */
async function openIfQueued(
  userId: string,
  existing?: DeviceStore | null,
): Promise<DeviceStore | null> {
  if (activeDeviceUser()?.toLowerCase() !== userId.toLowerCase()) return null;
  const reuse = existing?.open && existing.userId === userId ? existing : null;
  const store = reuse ?? (await DeviceStore.open(userId));
  if ((await store.queueCount()) > 0) {
    await store.putMeta(ENABLED_META, false);
    return store;
  }
  if (!reuse) store.close();
  return null;
}

/** How the refresh loads Core's data; the PWA shares its page queries. */
export interface ReadCacheLoaders {
  readonly board: (
    actionId: string,
  ) => Promise<AcquisitionActivityBoardResponse>;
  readonly capture: (
    actionId: string,
  ) => Promise<CommitmentCaptureContextResponse>;
}

/**
 * Replaces the read cache per acquirer action (§8.2) and drops what the
 * acquirer may no longer see: actions without an acquirer role and
 * documents past 14 days.
 */
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
  await purgeExpired(store, actions);
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
