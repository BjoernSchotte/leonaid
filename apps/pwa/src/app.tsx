import {
  Add01Icon,
  ArrowRight02Icon,
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

  useEffect(() => {
    const beforeInstall = (event: Event) => {
      event.preventDefault();
      setInstallPrompt(event as InstallPromptEvent);
    };
    const onOnline = () => setOnline(true);
    const onOffline = () => setOnline(false);
    const onUpdateAvailable = () => setUpdateReady(true);
    window.addEventListener("beforeinstallprompt", beforeInstall);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    window.addEventListener("leonaid:update-available", onUpdateAvailable);

    if ("serviceWorker" in navigator) {
      void navigator.serviceWorker
        .register("/app/sw.js", { scope: "/app/" })
        .then((value) => {
          registration.current = value;
          if (value.waiting) setUpdateReady(true);
          value.addEventListener("updatefound", () => {
            const worker = value.installing;
            worker?.addEventListener("statechange", () => {
              if (
                worker.state === "installed" &&
                navigator.serviceWorker.controller
              ) {
                setUpdateReady(true);
              }
            });
          });
          void value.update();
        });
      navigator.serviceWorker.addEventListener("controllerchange", () => {
        if (!reloading.current) {
          reloading.current = true;
          window.location.reload();
        }
      });
    }

    return () => {
      window.removeEventListener("beforeinstallprompt", beforeInstall);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      window.removeEventListener("leonaid:update-available", onUpdateAvailable);
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
      registration.current.waiting.postMessage({ type: "SKIP_WAITING" });
    } else {
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
            Aktualisiere LeonAid jetzt; offene Eingaben bleiben unberührt.
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

function Overview({
  displayName,
  memberships,
}: {
  readonly displayName: string;
  readonly memberships: ReadonlyArray<{
    readonly actionId: string;
    readonly actionName: string;
    readonly roleLabel: string;
  }>;
}) {
  return (
    <div className="pwa-overview">
      <header className="pwa-overview__header">
        <p>Dein Akquise-Tag</p>
        <h1>Guten Tag, {displayName.split(" ")[0]}.</h1>
        <span>
          Starte bei deinen Sponsoren oder dokumentiere den nächsten Kontakt.
        </span>
      </header>
      <div className="pwa-overview__actions">
        <a className="pwa-primary-path" href="/app/sponsors">
          <span aria-hidden="true">
            <HugeiconsIcon icon={Add01Icon} size={22} strokeWidth={1.9} />
          </span>
          <div>
            <strong>Meine Sponsoren öffnen</strong>
            <small>Zuständigkeiten, Kontakte und nächste Schritte</small>
          </div>
          <HugeiconsIcon
            aria-hidden="true"
            icon={ArrowRight02Icon}
            size={20}
            strokeWidth={1.9}
          />
        </a>
        <a className="pwa-secondary-path" href="/app/activities">
          Aktivität dokumentieren
          <HugeiconsIcon
            aria-hidden="true"
            icon={ArrowRight02Icon}
            size={18}
            strokeWidth={1.8}
          />
        </a>
      </div>
      <section aria-labelledby="pwa-actions-heading" className="pwa-actions">
        <h2 id="pwa-actions-heading">Deine aktiven Charity-Aktionen</h2>
        <div data-testid="action-list">
          {memberships.map((membership) => (
            <article
              data-action-id={membership.actionId}
              key={`${membership.actionId}-${membership.roleLabel}`}
            >
              <strong>{membership.actionName}</strong>
              <span>{membership.roleLabel}</span>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
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
    const nextUrl =
      next === "contacts" ? "/app/activities?view=contacts" : "/app/activities";
    window.history.replaceState({}, "", nextUrl);
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
        {route === "sponsors" ? (
          <SponsorWorkspace client={client} identity={identity.data} />
        ) : route === "commitment" ? (
          <CommitmentCapturePage client={client} identity={identity.data} />
        ) : route === "activities" ? (
          <ActivityHub client={client} identity={identity.data} />
        ) : (
          <Overview
            displayName={identity.data.displayName}
            memberships={memberships}
          />
        )}
      </AppShell>
      <PwaLifecycle />
    </>
  );
}
