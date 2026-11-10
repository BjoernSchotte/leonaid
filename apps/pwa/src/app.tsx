import { BellRing, Download, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import {
  ApiError,
  type CurrentIdentityResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  ActivityFeedPage,
  ActivityWorkspace,
  CommitmentCapturePage,
  FEATURE_FLAGS,
  FeatureFlagProvider,
  driverStanding,
  forgetPushDevice,
  ModuleSearch,
  navigateInPage,
  PushNotificationsPage,
  PwaDeliveryPage,
  PwaDriverStart,
  resolveModuleRoute,
  RoleDashboardPage,
  SponsorWorkspace,
  syncPushDevice,
  useCurrentActionId,
  useLeonAidSettledFlag,
  useLocationHref,
} from "@leonaid/features";
import {
  Button,
  buttonClassName,
  MobileShell,
  type MobileShellProps,
  StatusMessage,
} from "@leonaid/ui";

import {
  OfflineRuntimeContext,
  QueueSheet,
  OPEN_QUEUE_EVENT,
  SignOutWarning,
  pendingDeviceEntries,
  useOfflineRuntime,
  useQueueSnapshot,
  useTourCachePurge,
} from "@leonaid/features/offline";

import { forgetDevice, forgetSession } from "./device";
import { pwaModuleNavigationKeys, pwaModules, pwaPath } from "./modules";
import { mobileNavigation } from "./navigation";
import { queueIndicator, queueOfflineText } from "./queue-indicator";
import { useDevice } from "./use-device";
import {
  ADMIN_BASE,
  PWA_BASE,
  loginHref,
  redirectsToLogin,
  pwaHref,
  startAreaChoices,
} from "@leonaid/ui/base-paths";
import { hasBackOffice } from "@leonaid/features";

interface AppProps {
  readonly client: LeonAidApiClient;
}

interface InstallPromptEvent extends Event {
  readonly userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
  prompt(): Promise<void>;
}

type PwaRoute =
  | "overview"
  | "sponsors"
  | "commitment"
  | "follow-ups"
  | "news"
  | "delivery"
  | "notifications";

function currentRoute(): PwaRoute {
  const { pathname, search } = window.location;
  if (pathname.startsWith(pwaHref("commitments"))) return "commitment";
  if (pathname.startsWith(pwaHref("activities"))) {
    return new URLSearchParams(search).get("view") === "contacts"
      ? "follow-ups"
      : "news";
  }
  if (pathname.startsWith(pwaHref("sponsors"))) return "sponsors";
  if (pathname.startsWith(pwaHref("delivery"))) return "delivery";
  if (pathname.startsWith(pwaHref("notifications"))) return "notifications";
  return "overview";
}

// Core PWA pages; module pages come from the module registry.
const corePwaNavigation = [
  "overview-pwa",
  "sponsors",
  "commitment",
  "activities",
  "delivery",
];

interface PwaLifecycle {
  readonly online: boolean;
  readonly updateReady: boolean;
  readonly canInstall: boolean;
  readonly install: () => Promise<void>;
  readonly activateUpdate: () => void;
}

/** Service worker, update, install prompt and network state of the PWA. */
function usePwaLifecycle(): PwaLifecycle {
  const [installPrompt, setInstallPrompt] = useState<InstallPromptEvent | null>(
    null,
  );
  const [updateReady, setUpdateReady] = useState(false);
  const [online, setOnline] = useState(navigator.onLine);
  const registration = useRef<ServiceWorkerRegistration | null>(null);
  const reloading = useRef(false);
  const activationRequested = useRef(false);

  useEffect(() => {
    let disposed = false;
    let observedRegistration: ServiceWorkerRegistration | null = null;
    let observedWorker: ServiceWorker | null = null;
    const beforeInstall = (event: Event) => {
      event.preventDefault();
      setInstallPrompt(event as InstallPromptEvent);
    };
    const onOnline = () => setOnline(true);
    const onOffline = () => setOnline(false);
    const onUpdateAvailable = () => setUpdateReady(true);
    const onWorkerStateChange = () => {
      if (
        observedWorker?.state === "installed" &&
        navigator.serviceWorker.controller
      ) {
        setUpdateReady(true);
      }
    };
    const onUpdateFound = () => {
      observedWorker?.removeEventListener("statechange", onWorkerStateChange);
      observedWorker = observedRegistration?.installing ?? null;
      observedWorker?.addEventListener("statechange", onWorkerStateChange);
    };
    const onControllerChange = () => {
      if (activationRequested.current && !reloading.current) {
        reloading.current = true;
        window.location.reload();
      }
    };
    window.addEventListener("beforeinstallprompt", beforeInstall);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    window.addEventListener("leonaid:update-available", onUpdateAvailable);
    // A tapped notification: the worker names the page (sw.js); only
    // paths of this app are followed.
    const onWorkerMessage = (event: MessageEvent) => {
      const data = event.data as { type?: unknown; path?: unknown } | null;
      if (
        data?.type === "PUSH_NAVIGATE" &&
        typeof data.path === "string" &&
        data.path.startsWith(PWA_BASE)
      ) {
        navigateInPage(data.path);
      }
    };

    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.addEventListener("message", onWorkerMessage);
      navigator.serviceWorker.addEventListener(
        "controllerchange",
        onControllerChange,
      );
      void navigator.serviceWorker
        .register(pwaHref("sw.js"), { scope: PWA_BASE })
        .then((value) => {
          if (disposed) return;
          registration.current = value;
          observedRegistration = value;
          if (value.waiting) setUpdateReady(true);
          value.addEventListener("updatefound", onUpdateFound);
          void value.update().catch(() => {
            // A background update failure must not interrupt active work.
          });
        })
        .catch(() => {
          if (!disposed) {
            registration.current = null;
          }
        });
    }

    return () => {
      disposed = true;
      window.removeEventListener("beforeinstallprompt", beforeInstall);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      window.removeEventListener("leonaid:update-available", onUpdateAvailable);
      observedWorker?.removeEventListener("statechange", onWorkerStateChange);
      observedRegistration?.removeEventListener("updatefound", onUpdateFound);
      if ("serviceWorker" in navigator) {
        navigator.serviceWorker.removeEventListener("message", onWorkerMessage);
        navigator.serviceWorker.removeEventListener(
          "controllerchange",
          onControllerChange,
        );
      }
    };
  }, []);

  async function install() {
    if (!installPrompt) return;
    await installPrompt.prompt();
    await installPrompt.userChoice;
    setInstallPrompt(null);
  }

  function activateUpdate() {
    if (registration.current?.waiting) {
      activationRequested.current = true;
      registration.current.waiting.postMessage({ type: "SKIP_WAITING" });
    } else {
      activationRequested.current = false;
      setUpdateReady(false);
    }
  }

  return {
    activateUpdate,
    canInstall: installPrompt !== null,
    install,
    online,
    updateReady,
  };
}

/** Update and install notices; offline is the shell's own banner. */
function PwaNotices({ lifecycle }: { readonly lifecycle: PwaLifecycle }) {
  if (!lifecycle.online) return null;
  if (lifecycle.updateReady) {
    return (
      <aside aria-live="polite" className="pwa-notice" data-testid="pwa-update">
        <RefreshCw aria-hidden="true" size={16} />
        <span className="pwa-notice-text">
          <strong>Eine neue Version ist bereit.</strong> Speichere offene
          Eingaben vorher. Danach wird LeonAid neu geladen.
        </span>
        <Button onClick={lifecycle.activateUpdate} variant="secondary">
          Jetzt aktualisieren
        </Button>
      </aside>
    );
  }
  if (lifecycle.canInstall) {
    return (
      <aside
        aria-live="polite"
        className="pwa-notice"
        data-testid="pwa-install"
      >
        <Download aria-hidden="true" size={16} />
        <span className="pwa-notice-text">
          <strong>LeonAid griffbereit:</strong> Installiere die App auf deinem
          Startbildschirm.
        </span>
        <Button onClick={() => void lifecycle.install()} variant="secondary">
          Installieren
        </Button>
      </aside>
    );
  }
  return null;
}

const implementedPwaNavigation = new Set([
  ...corePwaNavigation,
  ...pwaModuleNavigationKeys,
]);

/**
 * The shell follows in-page URL changes (the sponsor capture view, Back),
 * so the active tab moves. Only the shell re-renders: the page element
 * comes from App unchanged, and module pages keep reading the URL
 * themselves.
 */
function PwaShell({
  client,
  driver,
  driverOnly,
  identity,
  navigation,
  ...props
}: Omit<MobileShellProps, "active" | "menuItems" | "tabs"> & {
  readonly client: LeonAidApiClient;
  readonly driver: boolean;
  readonly driverOnly: boolean;
  readonly identity: CurrentIdentityResponse;
  readonly navigation: CurrentIdentityResponse["navigation"];
}) {
  useLocationHref();
  // A flag switched off mid-session takes the driver's tour copy along.
  useTourCachePurge();
  const deliveryTours = useLeonAidSettledFlag(FEATURE_FLAGS.deliveryTours);
  const push = useLeonAidSettledFlag(FEATURE_FLAGS.pwaPush);
  // A device with push switched on tells Core where it is after every
  // sign-in: its subscription belongs to the session (ADR-0017).
  useEffect(() => {
    if (push !== true || props.offline) return;
    void syncPushDevice(client).catch(() => undefined);
  }, [client, push, props.offline]);
  const navigationState = mobileNavigation(
    navigation,
    implementedPwaNavigation,
    window.location,
    { deliveryTours, driver, driverOnly },
  );
  const { active, tabs } = navigationState;
  const notificationsHref = pwaHref("notifications");
  // "Benachrichtigungen" joins the "Mehr" sheet while `pwa.push` is on.
  const menu =
    push === true
      ? [
          ...navigationState.menu,
          {
            current: window.location.pathname.startsWith(notificationsHref),
            href: notificationsHref,
            icon: BellRing,
            key: "notifications",
            label: "Benachrichtigungen",
          },
        ]
      : navigationState.menu;
  const { sheet, ...queue } = useQueueShell(
    client,
    identity,
    !props.offline,
    deliveryTours === true &&
      identity.actionMemberships.some(
        (membership) => membership.role === "driver",
      ),
  );
  return (
    <>
      <MobileShell
        active={active}
        menuItems={menu}
        tabs={tabs}
        {...props}
        {...queue}
      />
      {sheet}
    </>
  );
}

/**
 * The capture queue in the shell (specs/pwa-offline-queue §12.1–§12.2):
 * the counter on the network glyph, the banner copy and the sheet. Without
 * a queue (flag off) the shell stays exactly as before.
 */
function useQueueShell(
  client: LeonAidApiClient,
  identity: CurrentIdentityResponse,
  online: boolean,
  /** Drives with tours on: marks and moves are queued too (§9). */
  driving: boolean,
): Pick<MobileShellProps, "offlineText" | "queue"> & {
  readonly sheet: ReactNode;
} {
  const { queue } = useOfflineRuntime();
  const snapshot = useQueueSnapshot();
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const show = () => setOpen(true);
    window.addEventListener(OPEN_QUEUE_EVENT, show);
    return () => window.removeEventListener(OPEN_QUEUE_EVENT, show);
  }, []);
  const actionNames = useMemo(
    () =>
      new Map(
        identity.actionMemberships.map(
          (membership) => [membership.actionId, membership.actionName] as const,
        ),
      ),
    [identity.actionMemberships],
  );
  if (!queue) return { sheet: null };
  const indicator = queueIndicator(snapshot);
  return {
    offlineText: (
      <>
        {queueOfflineText({
          acquirer: identity.actionMemberships.some(
            (membership) => membership.role === "acquirer",
          ),
          driver: driving,
        })}
        {indicator.waiting ? (
          <strong data-testid="offline-waiting">
            {` ${indicator.waiting} ${indicator.waiting === 1 ? "wartet" : "warten"} auf Versand.`}
          </strong>
        ) : null}
      </>
    ),
    queue: {
      count: indicator.count,
      label: indicator.label,
      onOpen: () => setOpen(true),
      state: indicator.state,
    },
    sheet: (
      <QueueSheet
        actionNames={actionNames}
        client={client}
        loginHref={loginHref(window.location)}
        onClose={() => setOpen(false)}
        online={online}
        open={open}
      />
    ),
  };
}

export function App({ client }: AppProps) {
  // In-page links between the acquirer screens switch the page here.
  useLocationHref();
  const currentActionId = useCurrentActionId();
  const lifecycle = usePwaLifecycle();
  const device = useDevice(client, lifecycle.online);
  const identity = device.identity;
  const [signOutOpen, setSignOutOpen] = useState(false);
  const [signOutCount, setSignOutCount] = useState<number | null>(0);
  function signOut() {
    // Sign-out deletes everything the PWA kept on this device (§8.5).
    // The device's push subscription ends too; Core deletes its copy
    // with the session.
    void forgetDevice(identity.data?.userId ?? null)
      .catch(() => undefined)
      .then(() => forgetPushDevice())
      .catch(() => undefined)
      .then(() => client.logout())
      .finally(() => {
        window.location.assign("/login");
      });
  }

  // Without a session: the deep link survives the login (specs/multi-domain
  // §6.7). An ended session shows the notice below first. The read cache
  // goes with the session; queued entries stay (offline queue §8.5).
  useEffect(() => {
    if (
      identity.error instanceof ApiError &&
      redirectsToLogin(identity.error)
    ) {
      void forgetSession(device.runtime.store)
        .catch(() => undefined)
        .finally(() => window.location.replace(loginHref(window.location)));
    }
  }, [identity.error]);

  if (identity.isPending) {
    return (
      <div aria-live="polite" className="pwa-loading" role="status">
        <span aria-hidden="true" />
        <h1>Arbeitsbereich wird geladen</h1>
        <p>Deine Charity-Aktionen und Zuständigkeiten werden abgerufen.</p>
      </div>
    );
  }

  if (identity.isError) {
    const signedOut =
      identity.error instanceof ApiError && identity.error.status === 401;
    return (
      <main className="ui-main">
        <StatusMessage tone="error">
          <div>
            <h1>
              {signedOut
                ? "Bitte erneut anmelden"
                : "Arbeitsbereich nicht erreichbar"}
            </h1>
            <p>
              {signedOut
                ? "Deine Sitzung ist abgelaufen oder dein Zugang wurde gesperrt."
                : "LeonAid konnte deine Zuständigkeiten gerade nicht laden. Prüfe deine Verbindung."}
            </p>
            {signedOut ? (
              <a
                className={buttonClassName({ variant: "primary" })}
                href={loginHref(window.location)}
              >
                Zur Anmeldung
              </a>
            ) : (
              <Button
                onClick={() => void identity.refetch()}
                variant="secondary"
              >
                Erneut versuchen
              </Button>
            )}
          </div>
        </StatusMessage>
      </main>
    );
  }

  // Core lists a module only while it is switched on and allowed.
  const availableModules = pwaModules.filter((module) =>
    identity.data.navigation.some((item) => item.key === module.id),
  );
  const moduleRoute = resolveModuleRoute(
    availableModules,
    "pwa",
    pwaPath(window.location.pathname),
  );
  const route = currentRoute();
  const memberships = identity.data.actionMemberships.filter(
    (membership) => membership.role === "acquirer",
  );
  // Drivers work in the actions they drive for; ?action= picks one.
  const driverActions = identity.data.actionMemberships.filter(
    (membership) => membership.role === "driver",
  );
  const driverActionId =
    driverActions.find((membership) => membership.actionId === currentActionId)
      ?.actionId ??
    driverActions[0]?.actionId ??
    "";
  const driverActionName = driverActions.find(
    (membership) => membership.actionId === driverActionId,
  )?.actionName;
  // The bar names the action the page works in: the tour's on the tour,
  // and never the acquirer's empty text for someone who only drives.
  const currentAction =
    (route === "delivery" ? driverActionName : undefined) ??
    memberships.find((membership) => membership.actionId === currentActionId)
      ?.actionName ??
    memberships[0]?.actionName ??
    driverActionName ??
    "Keine aktive Akquise-Aktion";
  const { driver, driverOnly } = driverStanding(
    identity.data.actionMemberships,
    currentActionId,
  );
  const atStart =
    window.location.pathname.replace(/\/+$/, "") ===
    PWA_BASE.replace(/\/+$/, "");

  // Members with back-office roles reach the admin app from here and may
  // choose the acquisition app as their start area (specs/multi-domain §6.7).
  const backOffice = hasBackOffice(identity.data.navigation);
  const surfaces = backOffice
    ? {
        switchTo: { label: "Zur Verwaltung", href: ADMIN_BASE },
        startAreas: startAreaChoices("pwa", identity.data, true).map(
          (choice) => ({
            label: choice.label,
            onSelect: () => {
              void client
                .setPreferredSurface({ surface: choice.surface })
                .then(() => identity.refetch());
            },
          }),
        ),
      }
    : undefined;

  return (
    <FeatureFlagProvider
      // Until Core's first answer in this page the flags are those of the
      // last online start, so an offline start shows the same pages (the
      // driver's tour needs `delivery.tours`) and reconnecting does not
      // flicker through "all off".
      cached={device.cachedFlags}
      client={client}
      identity={identity.data}
      surface="pwa"
    >
      <OfflineRuntimeContext.Provider value={device.runtime}>
        <PwaShell
          campaign={currentAction}
          client={client}
          driver={driver}
          driverOnly={driverOnly}
          identity={identity.data}
          navigation={identity.data.navigation}
          surfaces={surfaces}
          menuSearch={
            <ModuleSearch
              client={client}
              identity={identity.data}
              modules={availableModules}
              surface="pwa"
            />
          }
          notices={<PwaNotices lifecycle={lifecycle} />}
          offline={!lifecycle.online}
          onLogout={() => {
            // §12.5: captures still on the device would be deleted; ask
            // first. The store counts, not a view that may still be loading.
            // An unreadable queue asks too (count null).
            void pendingDeviceEntries(identity.data?.userId ?? null).then(
              (count) => {
                if (count === 0) {
                  signOut();
                } else {
                  setSignOutCount(count);
                  setSignOutOpen(true);
                }
              },
            );
          }}
          person={identity.data.displayName}
          role={identity.data.roleLabels.join(" · ")}
        >
          {moduleRoute ? (
            moduleRoute.render({ client, identity: identity.data })
          ) : route === "sponsors" ? (
            <SponsorWorkspace client={client} identity={identity.data} />
          ) : route === "commitment" ? (
            <CommitmentCapturePage client={client} identity={identity.data} />
          ) : route === "follow-ups" ? (
            <ActivityWorkspace client={client} identity={identity.data} />
          ) : route === "news" ? (
            <ActivityFeedPage client={client} surface="pwa" />
          ) : route === "notifications" ? (
            <PushNotificationsPage client={client} />
          ) : route === "delivery" ? (
            <PwaDeliveryPage
              actionId={driverActionId}
              actions={driverActions}
              client={client}
              offline={!lifecycle.online}
            />
          ) : driverOnly && atStart ? (
            <PwaDriverStart
              fallback={
                <RoleDashboardPage
                  client={client}
                  identity={identity.data}
                  mode="acquirer"
                />
              }
            />
          ) : (
            <RoleDashboardPage
              client={client}
              identity={identity.data}
              mode="acquirer"
            />
          )}
        </PwaShell>
        <SignOutWarning
          count={signOutCount}
          onCancel={() => setSignOutOpen(false)}
          onSendFirst={() => {
            // Send, and show what still needs a decision (L2 of #132).
            setSignOutOpen(false);
            void device.runtime.queue?.sendNow();
            window.dispatchEvent(new Event(OPEN_QUEUE_EVENT));
          }}
          onSignOut={() => {
            setSignOutOpen(false);
            signOut();
          }}
          online={lifecycle.online}
          open={signOutOpen}
        />
      </OfflineRuntimeContext.Provider>
    </FeatureFlagProvider>
  );
}
