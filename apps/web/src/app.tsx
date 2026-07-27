import { useQuery } from "@tanstack/react-query";

import { ApiError, type LeonAidApiClient } from "@leonaid/api-client";
import {
  ActionListPage,
  ActivityFeedPage,
  CommitmentAdminPage,
  CreateActionPage,
  FeatureFlagAdminPage,
  FeatureFlagProvider,
  InvoiceAdminPage,
  ManageActionPage,
  MemberInvitationPage,
  PreviewNotice,
} from "@leonaid/features";
import { AppShell, Button, StatusMessage } from "@leonaid/ui";

export interface AppProps {
  readonly client: LeonAidApiClient;
}

function route() {
  const pathname =
    window.location.pathname.replace(/^\/admin/, "").replace(/\/+$/, "") || "/";
  if (pathname === "/members") return { kind: "members" } as const;
  if (pathname === "/system") return { kind: "system" } as const;
  if (pathname === "/orders") return { kind: "orders" } as const;
  if (pathname === "/invoices") return { kind: "invoices" } as const;
  if (pathname === "/activities") return { kind: "activities" } as const;
  if (pathname === "/actions/new") return { kind: "new" } as const;
  const match = pathname.match(
    /^\/actions\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/,
  );
  if (match) return { actionId: match[1], kind: "manage" } as const;
  return { kind: "list" } as const;
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
          : currentRoute.kind === "orders"
            ? "Bestellungen"
            : currentRoute.kind === "invoices"
              ? "Rechnungen"
              : currentRoute.kind === "members"
                ? "Mitglieder"
                : currentRoute.kind === "system"
                  ? "System"
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
          <MemberInvitationPage client={client} />
        ) : currentRoute.kind === "orders" ? (
          <CommitmentAdminPage client={client} identity={identity.data} />
        ) : currentRoute.kind === "invoices" ? (
          <InvoiceAdminPage client={client} identity={identity.data} />
        ) : currentRoute.kind === "activities" ? (
          <ActivityFeedPage client={client} surface="web" />
        ) : currentRoute.kind === "system" ? (
          <FeatureFlagAdminPage client={client} />
        ) : (
          <ActionListPage identity={identity.data} />
        )}
      </AppShell>
    </FeatureFlagProvider>
  );
}
