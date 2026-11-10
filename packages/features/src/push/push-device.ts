/*
 * The browser's side of push notifications (specs/mails-documents-
 * donations-push §10, ADR-0017): whether this device can receive pushes,
 * its permission, and its subscription at the browser vendor's push
 * service. Core keeps the subscription's endpoint and keys; the device
 * keeps nothing else.
 */
import {
  ApiError,
  type LeonAidApiClient,
  type SavePushSubscriptionRequest,
} from "@leonaid/api-client";
import { PWA_BASE } from "@leonaid/ui/base-paths";

/**
 * - `supported`: the browser can ask for permission and subscribe.
 * - `needs-home-screen`: an iPhone or iPad in a browser tab; Web Push
 *   exists there only for a web app opened from the home screen.
 * - `unsupported`: no Web Push in this browser.
 */
export type PushSupport = "supported" | "needs-home-screen" | "unsupported";
export type PushPermission = "default" | "granted" | "denied";

/** The browser features the page needs; tests pass their own. */
export interface PushDevice {
  support(): PushSupport;
  permission(): PushPermission;
  requestPermission(): Promise<PushPermission>;
  /** The device's current subscription, if it has one. */
  subscription(): Promise<SavePushSubscriptionRequest | null>;
  /** Subscribes with the installation's public key (base64url). */
  subscribe(publicKey: string): Promise<SavePushSubscriptionRequest>;
  unsubscribe(): Promise<void>;
}

function base64UrlBytes(value: string): Uint8Array<ArrayBuffer> {
  const padded = value.replaceAll("-", "+").replaceAll("_", "/");
  const binary = atob(padded + "=".repeat((4 - (padded.length % 4)) % 4));
  const bytes = new Uint8Array(new ArrayBuffer(binary.length));
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function bytesBase64Url(value: ArrayBuffer | null): string {
  if (!value) return "";
  let binary = "";
  for (const byte of new Uint8Array(value)) binary += String.fromCharCode(byte);
  return btoa(binary)
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/, "");
}

function describe(
  subscription: PushSubscription,
): SavePushSubscriptionRequest | null {
  const p256dh = bytesBase64Url(subscription.getKey("p256dh"));
  const auth = bytesBase64Url(subscription.getKey("auth"));
  if (!p256dh || !auth) return null;
  return {
    // The key this subscription was made with. Empty when the browser does
    // not say: Core then refuses it, and the device subscribes again.
    applicationServerKey: bytesBase64Url(
      subscription.options?.applicationServerKey ?? null,
    ),
    endpoint: subscription.endpoint,
    keys: { auth, p256dh },
  };
}

/** iPhone and iPad; an iPad names itself a Mac but has a touch screen. */
function appleMobile(): boolean {
  return (
    /iPhone|iPad|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
  );
}

function fromHomeScreen(): boolean {
  return (
    (navigator as Navigator & { standalone?: boolean }).standalone === true ||
    window.matchMedia("(display-mode: standalone)").matches
  );
}

/** How long a start of the app may take to register its worker. */
const REGISTRATION_WAIT_MS = 10_000;

async function registration(): Promise<ServiceWorkerRegistration> {
  const found = await navigator.serviceWorker.getRegistration(PWA_BASE);
  if (found) return found;
  // The PWA registers its worker while it starts (app.tsx): wait for it.
  // A page without a worker would wait forever, hence the limit.
  return Promise.race([
    navigator.serviceWorker.ready,
    new Promise<never>((_, reject) => {
      setTimeout(
        () => reject(new Error("The service worker is not registered.")),
        REGISTRATION_WAIT_MS,
      );
    }),
  ]);
}

/** The real browser. */
export const browserPushDevice: PushDevice = {
  support() {
    if (
      "serviceWorker" in navigator &&
      "PushManager" in window &&
      "Notification" in window
    ) {
      return "supported";
    }
    return appleMobile() && !fromHomeScreen()
      ? "needs-home-screen"
      : "unsupported";
  },
  permission() {
    return Notification.permission;
  },
  async requestPermission() {
    return Notification.requestPermission();
  },
  async subscription() {
    const current = await (await registration()).pushManager.getSubscription();
    return current ? describe(current) : null;
  },
  async subscribe(publicKey) {
    const manager = (await registration()).pushManager;
    const options = {
      applicationServerKey: base64UrlBytes(publicKey),
      // Every push shows a notification (sw.js); browsers require it.
      userVisibleOnly: true,
    };
    let subscription: PushSubscription;
    try {
      subscription = await manager.subscribe(options);
    } catch (error) {
      // A subscription made with an earlier key of the installation
      // blocks a new one: end it and subscribe again.
      const stale = await manager.getSubscription();
      if (!stale) throw error;
      await stale.unsubscribe();
      subscription = await manager.subscribe(options);
    }
    const described = describe(subscription);
    if (!described) throw new Error("The subscription has no keys.");
    return described;
  },
  async unsubscribe() {
    const current = await (await registration()).pushManager.getSubscription();
    await current?.unsubscribe();
  },
};

/**
 * The device's subscription for the installation's current key, or null.
 *
 * A subscription made with an earlier key is dead: no push signed with the
 * current key reaches it. It is ended, and the device subscribes again
 * with the current key (the permission is still granted, so the browser
 * does not ask). Without permission nothing is asked of the browser.
 */
export async function liveSubscription(
  device: PushDevice,
  publicKey: string,
): Promise<SavePushSubscriptionRequest | null> {
  if (device.support() !== "supported" || device.permission() !== "granted") {
    return null;
  }
  const subscription = await device.subscription();
  if (!subscription || subscription.applicationServerKey === publicKey) {
    return subscription;
  }
  await device.unsubscribe();
  return device.subscribe(publicKey);
}

/**
 * Registers the device's subscription at Core; returns Core's id of it.
 *
 * Core answers `push_device_bound` when the endpoint is registered for
 * another account with other keys. A browser always sends the keys of its
 * own subscription, so for this browser that means: someone else holds the
 * row of this endpoint. The device ends its subscription, subscribes again
 * (a new endpoint) and registers that. Only if that fails too the caller
 * sees the error.
 */
export async function registerPushDevice(
  client: LeonAidApiClient,
  device: PushDevice,
  publicKey: string,
  subscription: SavePushSubscriptionRequest,
): Promise<string> {
  try {
    return (await client.savePushSubscription(subscription)).id;
  } catch (error) {
    if (
      !(error instanceof ApiError) ||
      error.detail.code !== "push_device_bound"
    ) {
      throw error;
    }
  }
  await device.unsubscribe();
  const fresh = await device.subscribe(publicKey);
  return (await client.savePushSubscription(fresh)).id;
}

/**
 * Keeps Core's copy of this device current: a subscription belongs to the
 * session that registered it, so after a new sign-in the device says again
 * where it is; and after the installation's key was replaced it subscribes
 * again. Does nothing without permission or without a subscription.
 * Returns Core's id of the device, or null.
 */
export async function syncPushDevice(
  client: LeonAidApiClient,
  device: PushDevice = browserPushDevice,
): Promise<string | null> {
  if (device.support() !== "supported" || device.permission() !== "granted") {
    return null;
  }
  // Without a subscription Core is not asked at all.
  if (!(await device.subscription())) return null;
  const { publicKey } = await client.getPushConfiguration();
  if (!publicKey) return null;
  const subscription = await liveSubscription(device, publicKey);
  if (!subscription) return null;
  return registerPushDevice(client, device, publicKey, subscription);
}

/** Sign-out never waits longer than this for the browser's push side. */
const FORGET_WAIT_MS = 3_000;

/**
 * Sign-out: ends the device's subscription at the push service. Core
 * deletes its copy when the session ends. Without the permission no
 * subscription exists, so the browser is not asked at all; and a browser
 * that does not answer (WebKit without a push service) must not hold the
 * sign-out, so the wait is bounded.
 */
export async function forgetPushDevice(
  device: PushDevice = browserPushDevice,
): Promise<void> {
  if (device.support() !== "supported" || device.permission() !== "granted") {
    return;
  }
  await Promise.race([
    device.unsubscribe(),
    new Promise<void>((resolve) => {
      setTimeout(resolve, FORGET_WAIT_MS);
    }),
  ]);
}
