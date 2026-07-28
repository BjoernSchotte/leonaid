import {
  Download04Icon,
  RefreshIcon,
  WifiDisconnected01Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useQuery } from "@tanstack/react-query";
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
  RoleDashboardPage,
  SponsorWorkspace,
} from "@leonaid/features";
import { AppShell, Button, StatusMessage } from "@leonaid/ui";

interface AppProps {
  readonly client: LeonAidApiClient;
}

interface InstallPromptEvent extends Event {
  readonly userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
  prompt(): Promise<void>;
}

function currentRoute() {
  if (window.location.pathname.startsWith("/app/commitments")) {
    return "commitment" as const;
  }
  if (window.location.pathname.startsWith("/app/activities")) {
    return "activities" as const;
  }
  if (window.location.pathname.startsWith("/app/sponsors")) {
    return "sponsors" as const;
  }
  return "overview" as const;
}

function PwaLifecycle() {
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

  if (!online) {
    return (
      <aside
        aria-live="polite"
        className="pwa-system-banner pwa-system-banner--offline"
        data-testid="offline-banner"
      >
        <HugeiconsIcon
          aria-hidden="true"
          icon={WifiDisconnected01Icon}
          size={20}
          strokeWidth={1.8}
        />
        <div>
          <strong>Du bist offline</strong>
          <span>
            Geöffnete Inhalte bleiben sichtbar. LeonAid speichert keine
            Änderungen im Hintergrund.
          </span>
        </div>
      </aside>
    );
  }

  if (updateReady) {
    return (
      <aside
        aria-live="polite"
        className="pwa-system-banner"
        data-testid="pwa-update"
      >
        <HugeiconsIcon
          aria-hidden="true"
          icon={RefreshIcon}
          size={20}
          strokeWidth={1.8}
        />
        <div>
          <strong>Eine neue Version ist bereit</strong>
          <span>
            Speichere offene Eingaben vorher. Danach wird LeonAid neu geladen.
          </span>
        </div>
        <Button onClick={activateUpdate} variant="secondary">
          Jetzt aktualisieren
        </Button>
      </aside>
    );
  }

  if (installPrompt) {
    return (
      <aside
        aria-live="polite"
        className="pwa-system-banner"
        data-testid="pwa-install"
      >
        <HugeiconsIcon
          aria-hidden="true"
          icon={Download04Icon}
          size={20}
          strokeWidth={1.8}
        />
        <div>
          <strong>LeonAid griffbereit</strong>
          <span>
            Installiere den Arbeitsbereich wie eine App auf diesem Gerät.
          </span>
        </div>
        <Button onClick={() => void install()} variant="secondary">
          Installieren
        </Button>
      </aside>
    );
  }

  return null;
}

function ActivityHub({
  client,
  identity,
}: {
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
}) {
  const [view, setView] = useState<"news" | "contacts">(() =>
    new URLSearchParams(window.location.search).get("view") === "contacts"
      ? "contacts"
      : "news",
  );

  function select(next: "news" | "contacts") {
    setView(next);
    const nextUrl = new URL(window.location.href);
    if (next === "contacts") nextUrl.searchParams.set("view", "contacts");
    else nextUrl.searchParams.delete("view");
    window.history.replaceState({}, "", `${nextUrl.pathname}${nextUrl.search}`);
  }

  return (
    <div className="activity-hub">
      <div
        aria-label="Aktivitätsbereich"
        className="activity-hub-tabs"
        role="tablist"
      >
        <button
          aria-controls="activity-news-panel"
          aria-selected={view === "news"}
          onClick={() => select("news")}
          role="tab"
          type="button"
        >
          Neues
        </button>
        <button
          aria-controls="activity-contacts-panel"
          aria-selected={view === "contacts"}
          onClick={() => select("contacts")}
          role="tab"
          type="button"
        >
          Kontakt dokumentieren
        </button>
      </div>
      {view === "news" ? (
        <div id="activity-news-panel" role="tabpanel">
          <ActivityFeedPage client={client} surface="pwa" />
        </div>
      ) : (
        <div id="activity-contacts-panel" role="tabpanel">
          <ActivityWorkspace client={client} identity={identity} />
        </div>
      )}
    </div>
  );
}

export function App({ client }: AppProps) {
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
              <a className="ui-button ui-button--primary" href="/login">
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

  const route = currentRoute();
  const memberships = identity.data.actionMemberships.filter(
    (membership) => membership.role === "acquirer",
  );
  const currentAction =
    memberships[0]?.actionName ?? "Keine aktive Akquise-Aktion";

  return (
    <>
      <AppShell
        currentActionName={currentAction}
        identity={identity.data}
        onLogout={() => {
          void client.logout().finally(() => {
            window.location.assign("/login");
          });
        }}
        surface="pwa"
      >
        <PwaLifecycle />
        {route === "sponsors" ? (
          <SponsorWorkspace client={client} identity={identity.data} />
        ) : route === "commitment" ? (
          <CommitmentCapturePage client={client} identity={identity.data} />
        ) : route === "activities" ? (
          <ActivityHub client={client} identity={identity.data} />
        ) : (
          <RoleDashboardPage
            client={client}
            identity={identity.data}
            mode="acquirer"
          />
        )}
      </AppShell>
    </>
  );
}
