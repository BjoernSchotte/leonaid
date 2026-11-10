/*
 * "Benachrichtigungen" of the acquisition app (specs/mails-documents-
 * donations-push §10): every state the page can be in, and what it asks
 * of the browser and of Core. The browser's push features are passed in
 * (PushDevice); Core answers through a real API client.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import axe from "axe-core";
import { describe, expect, it, vi } from "vitest";

import {
  LeonAidApiClient,
  type PushConfigurationResponse,
  type SavePushSubscriptionRequest,
} from "@leonaid/api-client";

import type {
  PushDevice,
  PushPermission,
  PushSupport,
} from "../../../packages/features/src/push/push-device";
import {
  forgetPushDevice,
  syncPushDevice,
} from "../../../packages/features/src/push/push-device";
import { PushNotificationsPage } from "../../../packages/features/src/push/push-notifications";

const PUBLIC_KEY =
  "BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8";
const OLD_KEY =
  "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4";
const SUBSCRIPTION: SavePushSubscriptionRequest = {
  applicationServerKey: PUBLIC_KEY,
  endpoint: "https://fcm.googleapis.com/fcm/send/device-1",
  keys: { auth: "BTBZMqHH6r4Tts7J_aSIgg", p256dh: PUBLIC_KEY },
};
const DEVICE_ID = "95620000-0000-4000-8000-0000000000b1";

interface SentRequest {
  readonly method: string;
  readonly path: string;
  readonly body: unknown;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

function failure(status: number, code: string): Response {
  return json(
    { error: { code, message: code, requestId: "push-test-1" } },
    status,
  );
}

interface CoreOptions {
  readonly configuration?: PushConfigurationResponse | Response;
  readonly test?: Response;
  /** Core's answer to a registration, instead of the device's id. */
  readonly subscribe?: Response;
}

const CONFIGURED: PushConfigurationResponse = {
  configured: true,
  kinds: [
    { enabled: false, kind: "follow_ups" },
    { enabled: true, kind: "feed" },
    { enabled: false, kind: "tasks" },
  ],
  publicKey: PUBLIC_KEY,
};

/** A real API client whose transport answers like the push endpoints. */
function core(sent: SentRequest[], options: CoreOptions = {}) {
  let configuration = options.configuration ?? CONFIGURED;
  return new LeonAidApiClient("", async (input, init = {}) => {
    const path = String(input);
    const method = init.method ?? "GET";
    const body = init.body ? (JSON.parse(String(init.body)) as unknown) : null;
    sent.push({ body, method, path });
    if (path === "/api/v1/push/configuration") {
      return configuration instanceof Response
        ? configuration.clone()
        : json(configuration);
    }
    if (path === "/api/v1/push/subscriptions") {
      return options.subscribe?.clone() ?? json({ id: DEVICE_ID });
    }
    if (path === `/api/v1/push/subscriptions/${DEVICE_ID}`) {
      return new Response(null, { status: 204 });
    }
    if (path === "/api/v1/push/preferences") {
      const change = (
        body as { preferences: { kind: string; enabled: boolean }[] }
      ).preferences[0]!;
      const current = configuration as PushConfigurationResponse;
      configuration = {
        ...current,
        kinds: current.kinds.map((item) =>
          item.kind === change.kind
            ? { ...item, enabled: change.enabled }
            : item,
        ),
      };
      return json(configuration);
    }
    if (path === "/api/v1/push/test") {
      return options.test?.clone() ?? json({ status: "queued" }, 202);
    }
    return failure(404, "endpoint_not_found");
  });
}

interface DeviceOptions {
  readonly support?: PushSupport;
  readonly permission?: PushPermission;
  /** What the browser's prompt answers. */
  readonly answer?: PushPermission;
  readonly subscribed?: boolean;
  /** The key the existing subscription was made with. */
  readonly subscribedKey?: string;
  readonly subscribeFails?: boolean;
}

/** A browser as the page sees it, with a record of what it was asked. */
function browser(options: DeviceOptions = {}) {
  const calls: string[] = [];
  let permission = options.permission ?? "default";
  let subscribed = options.subscribed ?? false;
  let key = options.subscribedKey ?? PUBLIC_KEY;
  const device: PushDevice = {
    permission: () => permission,
    requestPermission: async () => {
      calls.push("requestPermission");
      permission = options.answer ?? "granted";
      return permission;
    },
    subscribe: async (publicKey) => {
      calls.push(`subscribe:${publicKey}`);
      if (options.subscribeFails) throw new DOMException("no push service");
      subscribed = true;
      key = publicKey;
      return { ...SUBSCRIPTION, applicationServerKey: key };
    },
    subscription: async () =>
      subscribed ? { ...SUBSCRIPTION, applicationServerKey: key } : null,
    support: () => options.support ?? "supported",
    unsubscribe: async () => {
      calls.push("unsubscribe");
      subscribed = false;
    },
  };
  return { calls, device };
}

function show(client: LeonAidApiClient, device: PushDevice) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <PushNotificationsPage client={client} device={device} />
    </QueryClientProvider>,
  );
}

async function accessible(container: HTMLElement) {
  const result = await axe.run(container);
  expect(result.violations.map((violation) => violation.id)).toEqual([]);
}

describe("Benachrichtigungen", () => {
  it("says that the operator has not set push up", async () => {
    const sent: SentRequest[] = [];
    const { calls, device } = browser({ permission: "granted" });
    const { container } = show(
      core(sent, {
        configuration: { configured: false, kinds: [], publicKey: null },
      }),
      device,
    );
    expect(
      (await screen.findByTestId("push-not-configured")).textContent,
    ).toContain("noch nicht eingerichtet");
    expect(screen.queryByTestId("push-switch-on")).toBeNull();
    // Nothing is asked of the browser or of Core beyond the configuration.
    expect(calls).toEqual([]);
    expect(sent.map((request) => request.path)).toEqual([
      "/api/v1/push/configuration",
    ]);
    await accessible(container);
  });

  it("says that the club has not switched push on", async () => {
    const { device } = browser();
    show(
      core([], { configuration: failure(404, "feature_flag_disabled") }),
      device,
    );
    expect((await screen.findByTestId("push-disabled")).textContent).toContain(
      "nicht freigeschaltet",
    );
  });

  it("says that the browser cannot receive pushes", async () => {
    const { calls, device } = browser({ support: "unsupported" });
    const { container } = show(core([]), device);
    expect(
      (await screen.findByTestId("push-unsupported")).textContent,
    ).toContain("kann keine Benachrichtigungen empfangen");
    expect(calls).toEqual([]);
    await accessible(container);
  });

  it("explains the home screen on an iPhone in a browser tab", async () => {
    const { device } = browser({ support: "needs-home-screen" });
    const { container } = show(core([]), device);
    const note = await screen.findByTestId("push-home-screen");
    expect(note.textContent).toContain("Zum Home-Bildschirm");
    expect(note.querySelectorAll("li")).toHaveLength(3);
    expect(screen.queryByTestId("push-switch-on")).toBeNull();
    await accessible(container);
  });

  it("says where to lift a block in the browser", async () => {
    const { calls, device } = browser({ permission: "denied" });
    const { container } = show(core([]), device);
    expect((await screen.findByTestId("push-blocked")).textContent).toContain(
      "im Browser blockiert",
    );
    // A blocked browser is never asked again.
    expect(screen.queryByTestId("push-switch-on")).toBeNull();
    expect(calls).toEqual([]);
    await accessible(container);
  });

  it("explains the permission step, then registers the device", async () => {
    const sent: SentRequest[] = [];
    const { calls, device } = browser();
    const { container } = show(core(sent), device);
    const off = await screen.findByTestId("push-off");
    expect(off.textContent).toContain("Wähle dort „Zulassen“");
    expect(off.textContent).toContain("Home-Bildschirm");
    // Nothing is asked before the member decides.
    expect(calls).toEqual([]);
    await accessible(container);

    fireEvent.click(screen.getByTestId("push-switch-on"));
    await screen.findByTestId("push-on");
    expect(calls).toEqual(["requestPermission", `subscribe:${PUBLIC_KEY}`]);
    expect(sent.at(-1)).toEqual({
      body: SUBSCRIPTION,
      method: "PUT",
      path: "/api/v1/push/subscriptions",
    });
    await accessible(container);
  });

  it("keeps the device off when the member declines the prompt", async () => {
    const sent: SentRequest[] = [];
    const { calls, device } = browser({ answer: "denied" });
    show(core(sent), device);
    fireEvent.click(await screen.findByTestId("push-switch-on"));
    await screen.findByTestId("push-blocked");
    expect(calls).toEqual(["requestPermission"]);
    expect(sent.some((request) => request.method === "PUT")).toBe(false);
  });

  it("says so when the browser cannot subscribe", async () => {
    const { device } = browser({ subscribeFails: true });
    show(core([]), device);
    fireEvent.click(await screen.findByTestId("push-switch-on"));
    expect((await screen.findByTestId("push-notice")).textContent).toContain(
      "konnte nicht angemeldet werden",
    );
    expect(screen.getByTestId("push-off")).toBeTruthy();
  });

  it("offers one switch per kind and saves each change", async () => {
    const sent: SentRequest[] = [];
    const { device } = browser({ permission: "granted", subscribed: true });
    show(core(sent), device);
    await screen.findByTestId("push-on");
    // The device announced itself again (a new session after a sign-in).
    expect(sent.filter((request) => request.method === "PUT")).toEqual([
      {
        body: SUBSCRIPTION,
        method: "PUT",
        path: "/api/v1/push/subscriptions",
      },
    ]);
    const followUps = screen.getByTestId<HTMLInputElement>(
      "push-kind-follow_ups",
    );
    const feed = screen.getByTestId<HTMLInputElement>("push-kind-feed");
    expect(followUps.checked).toBe(false);
    expect(feed.checked).toBe(true);
    // Only the kinds Core offers this member: no switch for deliveries.
    expect(screen.queryByTestId("push-kind-delivery")).toBeNull();
    expect(screen.getByRole("switch", { name: "Wiedervorlagen" })).toBe(
      followUps,
    );

    fireEvent.click(followUps);
    await waitFor(() =>
      expect(
        screen.getByTestId<HTMLInputElement>("push-kind-follow_ups").checked,
      ).toBe(true),
    );
    fireEvent.click(feed);
    await waitFor(() =>
      expect(
        screen.getByTestId<HTMLInputElement>("push-kind-feed").checked,
      ).toBe(false),
    );
    expect(
      sent
        .filter((request) => request.path === "/api/v1/push/preferences")
        .map((request) => request.body),
    ).toEqual([
      { preferences: [{ enabled: true, kind: "follow_ups" }] },
      { preferences: [{ enabled: false, kind: "feed" }] },
    ]);
  });

  it("replaces a subscription of an earlier key instead of showing it as on", async () => {
    const sent: SentRequest[] = [];
    const { calls, device } = browser({
      permission: "granted",
      subscribed: true,
      subscribedKey: OLD_KEY,
    });
    show(core(sent), device);
    await screen.findByTestId("push-on");
    expect(calls).toEqual(["unsubscribe", `subscribe:${PUBLIC_KEY}`]);
    // Core never hears of the old key.
    expect(
      sent
        .filter((request) => request.method === "PUT")
        .map((request) => request.body),
    ).toEqual([SUBSCRIPTION]);
  });

  it("shows the device as off when the old subscription cannot be replaced", async () => {
    const sent: SentRequest[] = [];
    const { device } = browser({
      permission: "granted",
      subscribeFails: true,
      subscribed: true,
      subscribedKey: OLD_KEY,
    });
    show(core(sent), device);
    await screen.findByTestId("push-off");
    expect(screen.queryByTestId("push-on")).toBeNull();
    expect(sent.some((request) => request.method === "PUT")).toBe(false);
  });

  it("shows a subscribed device as on when Core takes no registration just now", async () => {
    const sent: SentRequest[] = [];
    const { calls, device } = browser({
      permission: "granted",
      subscribed: true,
    });
    const { container } = show(
      core(sent, { subscribe: failure(429, "push_rate_limited") }),
      device,
    );
    // The switches are there; the device is not shown as off.
    await screen.findByTestId("push-on");
    expect(screen.queryByTestId("push-off")).toBeNull();
    expect(screen.queryByTestId("push-switch-on")).toBeNull();
    expect(screen.getByTestId("push-busy").textContent).toContain(
      "in etwa einer Stunde noch einmal",
    );
    // Without Core's id of the device there is nothing to test or remove.
    expect(screen.queryByTestId("push-test")).toBeNull();
    expect(screen.queryByTestId("push-switch-off")).toBeNull();
    expect(calls).toEqual([]);
    // The switches still work.
    fireEvent.click(screen.getByTestId("push-kind-follow_ups"));
    await waitFor(() =>
      expect(
        screen.getByTestId<HTMLInputElement>("push-kind-follow_ups").checked,
      ).toBe(true),
    );
    await accessible(container);
  });

  it("says to try later when switching on hits the limit", async () => {
    const { device } = browser();
    show(core([], { subscribe: failure(429, "push_rate_limited") }), device);
    fireEvent.click(await screen.findByTestId("push-switch-on"));
    expect((await screen.findByTestId("push-notice")).textContent).toContain(
      "Versuche es in einer Stunde wieder",
    );
  });

  it("says so when the member has ten devices already", async () => {
    const { device } = browser();
    show(core([], { subscribe: failure(409, "push_device_limit") }), device);
    fireEvent.click(await screen.findByTestId("push-switch-on"));
    expect((await screen.findByTestId("push-notice")).textContent).toContain(
      "schon zehn Geräte",
    );
    expect(screen.getByTestId("push-off")).toBeTruthy();
  });

  it("sends a test push to this device", async () => {
    const sent: SentRequest[] = [];
    const { device } = browser({ permission: "granted", subscribed: true });
    show(core(sent), device);
    fireEvent.click(await screen.findByTestId("push-test"));
    expect((await screen.findByTestId("push-notice")).textContent).toContain(
      "Der Test ist unterwegs",
    );
    expect(sent.at(-1)).toEqual({
      body: { subscriptionId: DEVICE_ID },
      method: "POST",
      path: "/api/v1/push/test",
    });
  });

  it("says when too many tests were sent", async () => {
    const { device } = browser({ permission: "granted", subscribed: true });
    show(core([], { test: failure(429, "rate_limited") }), device);
    fireEvent.click(await screen.findByTestId("push-test"));
    expect((await screen.findByTestId("push-notice")).textContent).toContain(
      "viele Tests",
    );
  });

  it("switches the device off at the browser and at Core", async () => {
    const sent: SentRequest[] = [];
    const { calls, device } = browser({
      permission: "granted",
      subscribed: true,
    });
    show(core(sent), device);
    fireEvent.click(await screen.findByTestId("push-switch-off"));
    await screen.findByTestId("push-off");
    expect(calls).toEqual(["unsubscribe"]);
    expect(sent.at(-1)).toEqual({
      body: null,
      method: "DELETE",
      path: `/api/v1/push/subscriptions/${DEVICE_ID}`,
    });
  });
});

describe("the device outside the page", () => {
  it("tells Core where it is after a sign-in, only with permission", async () => {
    const sent: SentRequest[] = [];
    const subscribed = browser({ permission: "granted", subscribed: true });
    expect(await syncPushDevice(core(sent), subscribed.device)).toBe(DEVICE_ID);
    expect(sent).toEqual([
      { body: null, method: "GET", path: "/api/v1/push/configuration" },
      {
        body: SUBSCRIPTION,
        method: "PUT",
        path: "/api/v1/push/subscriptions",
      },
    ]);
    expect(subscribed.calls).toEqual([]);
    // No permission, no subscription or no support: Core hears nothing.
    for (const options of [
      { subscribed: true },
      { permission: "granted" },
      { permission: "granted", subscribed: true, support: "unsupported" },
    ] as const) {
      const quiet: SentRequest[] = [];
      expect(await syncPushDevice(core(quiet), browser(options).device)).toBe(
        null,
      );
      expect(quiet).toEqual([]);
    }
  });

  it("subscribes again at start after the installation's key was replaced", async () => {
    const sent: SentRequest[] = [];
    const stale = browser({
      permission: "granted",
      subscribed: true,
      subscribedKey: OLD_KEY,
    });
    expect(await syncPushDevice(core(sent), stale.device)).toBe(DEVICE_ID);
    // The dead subscription is ended; the new one carries the current key.
    expect(stale.calls).toEqual(["unsubscribe", `subscribe:${PUBLIC_KEY}`]);
    expect(sent.at(-1)).toEqual({
      body: SUBSCRIPTION,
      method: "PUT",
      path: "/api/v1/push/subscriptions",
    });
    // Without a key at Core nothing is touched.
    const untouched = browser({
      permission: "granted",
      subscribed: true,
      subscribedKey: OLD_KEY,
    });
    expect(
      await syncPushDevice(
        core([], {
          configuration: { configured: false, kinds: [], publicKey: null },
        }),
        untouched.device,
      ),
    ).toBe(null);
    expect(untouched.calls).toEqual([]);
  });

  it("ends the browser's subscription at sign-out", async () => {
    const signedIn = browser({ permission: "granted", subscribed: true });
    await forgetPushDevice(signedIn.device);
    expect(signedIn.calls).toEqual(["unsubscribe"]);
    expect(await signedIn.device.subscription()).toBeNull();
    // Without support or without the permission the browser is not asked.
    for (const options of [
      { support: "unsupported" },
      { permission: "default" },
      { permission: "denied" },
    ] as const) {
      const quiet = browser(options);
      await forgetPushDevice(quiet.device);
      expect(quiet.calls).toEqual([]);
    }
  });

  it("does not hold the sign-out when the browser never answers", async () => {
    vi.useFakeTimers();
    try {
      const { device } = browser({ permission: "granted", subscribed: true });
      const silent = {
        ...device,
        unsubscribe: () => new Promise<void>(() => {}),
      };
      let done = false;
      const forgotten = forgetPushDevice(silent).then(() => {
        done = true;
      });
      await vi.advanceTimersByTimeAsync(2_999);
      expect(done).toBe(false);
      await vi.advanceTimersByTimeAsync(1);
      await forgotten;
      expect(done).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });
});
