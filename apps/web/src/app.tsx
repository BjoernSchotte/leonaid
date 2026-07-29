import { useQuery } from "@tanstack/react-query";

import { ApiError, type LeonAidApiClient } from "@leonaid/api-client";
import {
  ActionListPage,
  AcquisitionAdminPage,
  ActivityFeedPage,
  CommitmentAdminPage,
  CreateActionPage,
  FeatureFlagAdminPage,
  FeatureFlagProvider,
  InvoiceAdminPage,
  LegalConfigurationPage,
  ManageActionPage,
  MemberAdministrationPage,
  PrivacyAdminPage,
  PreviewNotice,
  RoleDashboardPage,
  UiSystemCatalogPage,
} from "@leonaid/features";
import { AppShell, Button, StatusMessage } from "@leonaid/ui";

export interface AppProps {
  readonly client: LeonAidApiClient;
}

function route() {
  const pathname =
    window.location.pathname.replace(/^\/admin/, "").replace(/\/+$/, "") || "/";
  if (pathname === "/") return { kind: "dashboard" } as const;
  if (pathname === "/actions") return { kind: "list" } as const;
  if (pathname === "/members") return { kind: "members" } as const;
  if (pathname === "/system") return { kind: "system" } as const;
  if (pathname === "/privacy") return { kind: "privacy" } as const;
  if (pathname === "/legal") return { kind: "legal" } as const;
  if (pathname === "/system/ui") return { kind: "system-ui" } as const;
  if (pathname === "/orders") return { kind: "orders" } as const;
  if (pathname === "/invoices") return { kind: "invoices" } as const;
  if (pathname === "/activities") return { kind: "activities" } as const;
  if (pathname === "/acquisition") return { kind: "acquisition" } as const;
  if (pathname === "/actions/new") return { kind: "new" } as const;
  const match = pathname.match(
    /^\/actions\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/,
  );
  if (match) return { actionId: match[1], kind: "manage" } as const;
  return { kind: "dashboard" } as const;
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
      <div aria-live="polite" className="action-loading" role="status">
        <span aria-hidden="true" />
        <h1>Arbeitsbereich wird geladen</h1>
        <p>Deine Rollen und Charity-Aktionen werden sicher abgerufen.</p>
      </div>
    );
  }

  if (identity.isError) {
    const signedOut =
      identity.error instanceof ApiError && identity.error.status === 401;
    return (
      <main className="ui-main">
        <StatusMessage tone="error">
          <h1>
            {signedOut
              ? "Bitte erneut anmelden"
              : "Arbeitsbereich nicht erreichbar"}
          </h1>
          <p>
            {signedOut
              ? "Deine Sitzung ist abgelaufen oder dein Zugang wurde gesperrt."
              : "LeonAid konnte deine Rollen gerade nicht laden. Versuche es bitte noch einmal."}
          </p>
          {signedOut ? (
            <a className="ui-button ui-button--primary" href="/login">
              Zur Anmeldung
            </a>
          ) : (
            <Button onClick={() => void identity.refetch()} variant="secondary">
              Erneut versuchen
            </Button>
          )}
        </StatusMessage>
      </main>
    );
  }

  const currentRoute = route();
  const currentAction =
    currentRoute.kind === "manage"
      ? (identity.data.actionMemberships.find(
          (item) => item.actionId === currentRoute.actionId,
        )?.actionName ?? "Aktion verwalten")
      : currentRoute.kind === "new"
        ? "Neue Aktion"
        : currentRoute.kind === "activities"
          ? "Neues"
          : currentRoute.kind === "acquisition"
            ? "Akquise"
            : currentRoute.kind === "orders"
              ? "Bestellungen"
              : currentRoute.kind === "invoices"
                ? "Rechnungen"
                : currentRoute.kind === "members"
                  ? "Mitglieder"
                  : currentRoute.kind === "system"
                    ? "System"
                    : currentRoute.kind === "privacy"
                      ? "Datenschutz"
                      : currentRoute.kind === "legal"
                        ? "Organisation & Recht"
                        : currentRoute.kind === "system-ui"
                          ? "UI-Basis"
                          : currentRoute.kind === "dashboard"
                            ? (identity.data.actionMemberships.find(
                                (item) =>
                                  item.role === "charity_admin" &&
                                  item.actionId ===
                                    new URLSearchParams(
                                      window.location.search,
                                    ).get("action"),
                              )?.actionName ??
                              identity.data.actionMemberships.find(
                                (item) => item.role === "charity_admin",
                              )?.actionName ??
                              "Charity-Übersicht")
                            : "Alle Aktionen";

  return (
    <FeatureFlagProvider client={client} identity={identity.data} surface="web">
      <AppShell
        currentActionName={currentAction}
        identity={identity.data}
        onLogout={() => {
          void client.logout().finally(() => {
            window.location.assign("/login");
          });
        }}
      >
        <PreviewNotice />
        {currentRoute.kind === "new" ? (
          <CreateActionPage client={client} />
        ) : currentRoute.kind === "manage" ? (
          <ManageActionPage
            actionId={currentRoute.actionId}
            client={client}
            key={currentRoute.actionId}
          />
        ) : currentRoute.kind === "members" ? (
          <MemberAdministrationPage client={client} identity={identity.data} />
        ) : currentRoute.kind === "orders" ? (
          <CommitmentAdminPage client={client} identity={identity.data} />
        ) : currentRoute.kind === "invoices" ? (
          <InvoiceAdminPage client={client} identity={identity.data} />
        ) : currentRoute.kind === "activities" ? (
          <ActivityFeedPage client={client} surface="web" />
        ) : currentRoute.kind === "acquisition" ? (
          <AcquisitionAdminPage client={client} identity={identity.data} />
        ) : currentRoute.kind === "system" ? (
          <FeatureFlagAdminPage client={client} />
        ) : currentRoute.kind === "privacy" ? (
          <PrivacyAdminPage client={client} />
        ) : currentRoute.kind === "legal" ? (
          <LegalConfigurationPage client={client} identity={identity.data} />
        ) : currentRoute.kind === "system-ui" ? (
          <UiSystemCatalogPage identity={identity.data} />
        ) : currentRoute.kind === "dashboard" ? (
          <RoleDashboardPage
            client={client}
            identity={identity.data}
            mode="charity_admin"
          />
        ) : (
          <ActionListPage identity={identity.data} />
        )}
      </AppShell>
    </FeatureFlagProvider>
  );
}
