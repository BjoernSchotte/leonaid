import { useQuery } from "@tanstack/react-query";
import { Download, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  ApiError,
  type CurrentIdentityResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  ActivityFeedPage,
  ActivityWorkspace,
  CommitmentCapturePage,
  DeliveryBoardPage,
  ModuleSearch,
  resolveModuleRoute,
  RoleDashboardPage,
  SponsorWorkspace,
  useCurrentActionId,
  useLocationHref,
} from "@leonaid/features";
import {
  Button,
  buttonClassName,
  MobileShell,
  type MobileShellProps,
  StatusMessage,
} from "@leonaid/ui";

import { pwaModuleNavigationKeys, pwaModules, pwaPath } from "./modules";
import { mobileNavigation } from "./navigation";

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
  | "delivery";

function currentRoute(): PwaRoute {
  const { pathname, search } = window.location;
  if (pathname.startsWith("/app/commitments")) return "commitment";
  if (pathname.startsWith("/app/activities")) {
    return new URLSearchParams(search).get("view") === "contacts"
      ? "follow-ups"
      : "news";
  }
  if (pathname.startsWith("/app/sponsors")) return "sponsors";
  if (pathname.startsWith("/app/delivery")) return "delivery";
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

    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.addEventListener(
        "controllerchange",
        onControllerChange,
      );
      void navigator.serviceWorker
        .register("/app/sw.js", { scope: "/app/" })
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
  navigation,
  ...props
}: Omit<MobileShellProps, "active" | "menuItems" | "tabs"> & {
  readonly navigation: CurrentIdentityResponse["navigation"];
}) {
  useLocationHref();
  const { active, menu, tabs } = mobileNavigation(
    navigation,
    implementedPwaNavigation,
    window.location,
  );
  return (
    <MobileShell active={active} menuItems={menu} tabs={tabs} {...props} />
  );
}

export function App({ client }: AppProps) {
  const currentActionId = useCurrentActionId();
  const lifecycle = usePwaLifecycle();
  const identity = useQuery({
    queryFn: () => client.getCurrentIdentity(),
    queryKey: ["identity"],
    retry: (failureCount, error) =>
      !(error instanceof ApiError) && failureCount < 2,
    retryDelay: (attempt) => 150 * (attempt + 1),
    staleTime: 30_000,
  });

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
                href="/login"
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
  const currentAction =
    memberships.find((membership) => membership.actionId === currentActionId)
      ?.actionName ??
    memberships[0]?.actionName ??
    "Keine aktive Akquise-Aktion";

  return (
    <PwaShell
      campaign={currentAction}
      navigation={identity.data.navigation}
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
        void client.logout().finally(() => {
          window.location.assign("/login");
        });
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
      ) : route === "delivery" ? (
        <DeliveryBoardPage
          actionId={driverActionId}
          actions={driverActions}
          client={client}
          offline={!lifecycle.online}
          surface="pwa"
        />
      ) : (
        <RoleDashboardPage
          client={client}
          identity={identity.data}
          mode="acquirer"
        />
      )}
    </PwaShell>
  );
}
