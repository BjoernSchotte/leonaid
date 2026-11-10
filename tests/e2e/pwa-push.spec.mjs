// Push notifications in the acquisition app (specs/mails-documents-
// donations-push §10, ADR-0017), in a real Chromium against the real stack:
// the page "Benachrichtigungen" and the service worker's `push` and
// `notificationclick` handlers.
//
// The pushes of this spec are synthetic: Chromium's DevTools protocol hands
// the installed service worker a push message (ServiceWorker.
// deliverPushMessage). No push service of a browser vendor is part of this
// proof; the test stack has no route to one. Sending is proven in
// tests/integration/test_push_api.py against a receiver that decrypts.
//
// tools/pwa/test.sh runs "flag off" first, switches `pwa.push` on and then
// runs the other tests.
import { analyzeAccessibility, WCAG_TAGS } from "./axe.mjs";
import { expect, test } from "./csp-guard.mjs";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const annaSession = process.env.ANNA_SESSION;

if (!baseUrl || !artifactDirectory || !annaSession) {
  throw new Error(
    "LEONAID_E2E_BASE_URL, LEONAID_E2E_ARTIFACT_DIR und ANNA_SESSION sind erforderlich",
  );
}

test.use({
  // The full Chromium in its new headless mode: the headless shell that
  // Playwright starts by default refuses every notification permission.
  channel: "chromium",
  ignoreHTTPSErrors: true,
  launchOptions: { args: ["--ignore-certificate-errors"] },
  viewport: { width: 390, height: 844 },
});

async function authenticate(context) {
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: annaSession,
      url: baseUrl,
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
    },
  ]);
}

/** Opens the app and waits until its service worker controls the page. */
async function openApp(page, path = "/app/") {
  await page.goto(`${baseUrl}${path}`);
  await expect(page.locator('[data-testid="display-name"]')).toHaveText(
    "Anna Akquise",
  );
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
  });
}

/** The DevTools registration id of the app's service worker. */
async function workerRegistration(context, page) {
  const session = await context.newCDPSession(page);
  const found = new Promise((resolve) => {
    session.on("ServiceWorker.workerRegistrationUpdated", (event) => {
      const registration = event.registrations.find((item) =>
        item.scopeURL.endsWith("/app/"),
      );
      if (registration) resolve(registration.registrationId);
    });
  });
  await session.send("ServiceWorker.enable");
  return { registrationId: await found, session };
}

async function deliverPush(session, registrationId, data) {
  await session.send("ServiceWorker.deliverPushMessage", {
    data: typeof data === "string" ? data : JSON.stringify(data),
    origin: new URL(baseUrl).origin,
    registrationId,
  });
}

/** What the device shows: the notifications of the app's registration. */
function shownNotifications(page) {
  return page.evaluate(async () => {
    const registration = await navigator.serviceWorker.ready;
    return (await registration.getNotifications()).map((notification) => ({
      body: notification.body,
      data: notification.data,
      tag: notification.tag,
      title: notification.title,
    }));
  });
}

test("flag off: no entry in the menu, and the page says so", async ({
  context,
  page,
}) => {
  await authenticate(context);
  await openApp(page);
  await page.getByRole("button", { name: "Mehr" }).click();
  const sheet = page.locator('[data-testid="pwa-sheet"]');
  await expect(sheet).toBeVisible();
  await expect(sheet.getByText("Benachrichtigungen")).toHaveCount(0);

  await page.goto(`${baseUrl}/app/notifications`);
  await expect(page.locator('[data-testid="push-disabled"]')).toContainText(
    "nicht freigeschaltet",
  );
  await expect(page.locator('[data-testid="push-switch-on"]')).toHaveCount(0);
});

test("the page explains the permission step and a blocked browser", async ({
  context,
  page,
}) => {
  await authenticate(context);
  await openApp(page);

  // "Benachrichtigungen" is in the "Mehr" sheet while the flag is on.
  await page.getByRole("button", { name: "Mehr" }).click();
  const entry = page
    .locator('[data-testid="pwa-sheet"]')
    .getByRole("link", { name: "Benachrichtigungen" });
  await expect(entry).toBeVisible();
  await entry.click();
  await expect(page).toHaveURL(/\/app\/notifications$/);
  await expect(
    page.getByRole("heading", { level: 1, name: "Benachrichtigungen" }),
  ).toBeVisible();

  // This browser has not been asked, or (headless) refuses on its own:
  // the page shows the matching state, never a switch that cannot work.
  const permission = await page.evaluate(() => Notification.permission);
  if (permission === "denied") {
    await expect(page.locator('[data-testid="push-blocked"]')).toContainText(
      "im Browser blockiert",
    );
    await expect(page.locator('[data-testid="push-switch-on"]')).toHaveCount(0);
  } else {
    await expect(page.locator('[data-testid="push-off"]')).toContainText(
      "Wähle dort „Zulassen“",
    );
  }

  // With the permission granted and no subscription yet: the step that
  // asks, with the note for iPhone and iPad.
  await context.grantPermissions(["notifications"], {
    origin: new URL(baseUrl).origin,
  });
  await page.reload();
  const off = page.locator('[data-testid="push-off"]');
  await expect(off).toContainText("Auf diesem Gerät einschalten");
  await expect(off).toContainText("Home-Bildschirm");
  await expect(page.locator('[data-testid="push-not-configured"]')).toHaveCount(
    0,
  );
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  const results = await analyzeAccessibility(page, { tags: WCAG_TAGS });
  expect(
    results.violations
      .filter(({ impact }) => ["critical", "serious"].includes(impact))
      .map((violation) => violation.id),
  ).toEqual([]);
  await page.screenshot({
    fullPage: true,
    path: `${artifactDirectory}/pwa-push-chromium-390.png`,
  });

  // The test stack reaches no push service: switching on fails, and the
  // page says so instead of pretending.
  await page.locator('[data-testid="push-switch-on"]').click();
  await expect(page.locator('[data-testid="push-notice"]')).toContainText(
    "konnte nicht angemeldet werden",
    { timeout: 60_000 },
  );
  await expect(off).toBeVisible();
});

test("a subscribed device gets its switches, and they are saved", async ({
  context,
  page,
}) => {
  await authenticate(context);
  await context.grantPermissions(["notifications"], {
    origin: new URL(baseUrl).origin,
  });
  // The test stack reaches no push service of a browser vendor, so the
  // browser cannot make a subscription. This test hands the page a
  // subscription as PushManager would (an endpoint and a fresh P-256 key).
  // Everything behind it is real: Core checks the endpoint and the keys,
  // stores the device and the switches.
  await context.addInitScript(() => {
    // Kept in localStorage, as a browser keeps a subscription over reloads.
    const KEY = "e2e-push-subscription";
    const encode = (bytes) =>
      btoa(String.fromCharCode(...new Uint8Array(bytes)));
    const decode = (text) =>
      Uint8Array.from(atob(text), (character) => character.charCodeAt(0))
        .buffer;
    const load = () => {
      const stored = localStorage.getItem(KEY);
      if (!stored) return null;
      const value = JSON.parse(stored);
      return {
        endpoint: value.endpoint,
        getKey: (name) => decode(value[name]),
        unsubscribe: async () => {
          localStorage.removeItem(KEY);
          return true;
        },
      };
    };
    PushManager.prototype.getSubscription = async () => load();
    PushManager.prototype.subscribe = async () => {
      const pair = await crypto.subtle.generateKey(
        { name: "ECDH", namedCurve: "P-256" },
        true,
        ["deriveBits"],
      );
      const auth = crypto.getRandomValues(new Uint8Array(16));
      const p256dh = await crypto.subtle.exportKey("raw", pair.publicKey);
      const name = encode(auth).replaceAll(/[^A-Za-z0-9]/g, "");
      localStorage.setItem(
        KEY,
        JSON.stringify({
          auth: encode(auth),
          endpoint: `https://fcm.googleapis.com/fcm/send/e2e-${name}`,
          p256dh: encode(p256dh),
        }),
      );
      return load();
    };
  });
  await openApp(page, "/app/notifications");

  await page.locator('[data-testid="push-switch-on"]').click();
  const on = page.locator('[data-testid="push-on"]');
  await expect(on).toBeVisible();
  // Anna acquires: follow-ups, new orders and tasks, no deliveries.
  const followUps = page.getByRole("switch", { name: "Wiedervorlagen" });
  const orders = page.getByRole("switch", { name: "Neue Bestellungen" });
  await expect(page.getByRole("switch", { name: "Aufgaben" })).toBeVisible();
  await expect(page.getByRole("switch", { name: "Lieferungen" })).toHaveCount(
    0,
  );
  // Each kind is off until the member switches it on.
  await expect(followUps).not.toBeChecked();
  await expect(orders).not.toBeChecked();
  // The switch moves once Core has saved it.
  await followUps.click();
  await expect(followUps).toBeChecked();
  const results = await analyzeAccessibility(page, { tags: WCAG_TAGS });
  expect(
    results.violations
      .filter(({ impact }) => ["critical", "serious"].includes(impact))
      .map((violation) => violation.id),
  ).toEqual([]);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  await page.screenshot({
    fullPage: true,
    path: `${artifactDirectory}/pwa-push-on-chromium-390.png`,
  });
  // Desktop width: the same page in a wide window.
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({
    fullPage: true,
    path: `${artifactDirectory}/pwa-push-on-chromium-1440.png`,
  });
  await page.setViewportSize({ width: 390, height: 844 });

  // Core kept the device and the switch: a fresh load shows both again.
  await page.reload();
  await expect(
    page.getByRole("switch", { name: "Wiedervorlagen" }),
  ).toBeChecked();

  // Back to the start: the kind off, the device removed at Core.
  await page.getByRole("switch", { name: "Wiedervorlagen" }).click();
  await expect(
    page.getByRole("switch", { name: "Wiedervorlagen" }),
  ).not.toBeChecked();
  await page.locator('[data-testid="push-switch-off"]').click();
  await expect(page.locator('[data-testid="push-off"]')).toBeVisible();
});

test("a push shows a notification, and a tap opens its page", async ({
  context,
  page,
}) => {
  await authenticate(context);
  await context.grantPermissions(["notifications"], {
    origin: new URL(baseUrl).origin,
  });
  await openApp(page, "/app/sponsors");
  const { registrationId, session } = await workerRegistration(context, page);

  // Kind, count and path arrive; the text is written on the device.
  await deliverPush(session, registrationId, {
    count: 3,
    kind: "follow_ups",
    path: "/app/activities?view=contacts",
  });
  await expect
    .poll(() => shownNotifications(page))
    .toEqual([
      {
        body: "3 Wiedervorlagen sind fällig.",
        data: { path: "/app/activities?view=contacts" },
        tag: "leonaid-follow_ups",
        title: "LeonAid",
      },
    ]);

  // A second push of the same kind replaces the first; another kind adds.
  await deliverPush(session, registrationId, {
    count: 1,
    kind: "follow_ups",
    path: "/app/activities?view=contacts",
  });
  await deliverPush(session, registrationId, {
    count: 2,
    kind: "tasks",
    path: "/app/tasks",
  });
  await expect
    .poll(async () =>
      (await shownNotifications(page)).map((item) => item.body).sort(),
    )
    .toEqual([
      "1 Wiedervorlage ist fällig.",
      "Dir wurden 2 Aufgaben zugewiesen.",
    ]);

  // A push the worker cannot read still shows a notification, and one
  // with a path outside the app leads to the app's start.
  await deliverPush(session, registrationId, "not json");
  await deliverPush(session, registrationId, {
    count: 1,
    kind: "feed",
    path: "https://attacker.example/",
  });
  await expect
    .poll(async () =>
      (await shownNotifications(page))
        .filter((item) => ["leonaid-news", "leonaid-feed"].includes(item.tag))
        .map((item) => [item.tag, item.body, item.data.path])
        .sort(),
    )
    .toEqual([
      ["leonaid-feed", "Es gibt eine neue Bestellung unter „Neues“.", "/app/"],
      ["leonaid-news", "Es gibt Neues in LeonAid.", "/app/"],
    ]);

  // The tap on the follow-up notification: the worker gets the browser's
  // own event for the shown notification; the open app moves to the page.
  const [worker] = context.serviceWorkers();
  expect(worker, "the app's service worker").toBeTruthy();
  await worker.evaluate(async () => {
    const notifications = await self.registration.getNotifications({
      tag: "leonaid-follow_ups",
    });
    self.dispatchEvent(
      new NotificationEvent("notificationclick", {
        notification: notifications[0],
      }),
    );
  });
  await expect(page).toHaveURL(/\/app\/activities\?view=contacts$/);
  await expect(
    page.getByRole("heading", { level: 1, name: "Wiedervorlagen" }),
  ).toBeVisible();
  // The tapped notification is closed, the others stay.
  await expect
    .poll(async () =>
      (await shownNotifications(page)).map((item) => item.tag).sort(),
    )
    .toEqual(["leonaid-feed", "leonaid-news", "leonaid-tasks"]);
});
