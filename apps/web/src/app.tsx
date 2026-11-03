import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { ApiError, type LeonAidApiClient } from "@leonaid/api-client";
import {
  ActionListPage,
  AcquisitionAdminPage,
  ActivityFeedPage,
  CommandPalette,
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
  useCurrentActionId,
  campaignEditorHref,
  railCampaigns,
  railNavigation,
  resolveModuleRoute,
  useCommandPalette,
  type PaletteCommand,
  type UiModule,
} from "@leonaid/features";
import { Moon, Sun } from "lucide-react";

import {
  activeNavigationKey,
  Button,
  buttonClassName,
  RailShell,
  setThemePreference,
  StatusMessage,
  toggleTheme,
} from "@leonaid/ui";

import { webModules } from "./modules";

/** Shell commands of the palette's "Einstellungen" section (prototype). */
const themeCommands: readonly PaletteCommand[] = [
  {
    id: "theme-toggle",
    label: "Hell/Dunkel wechseln",
    group: "Einstellungen",
    icon: Moon,
    keys: "shift+t",
    keywords: ["Theme", "Darstellung", "dunkel", "hell"],
    run: () => void toggleTheme(),
  },
  {
    id: "theme-system",
    label: "Darstellung wie System",
    group: "Einstellungen",
    icon: Sun,
    keywords: ["Theme", "Systemeinstellung", "folgen"],
    run: () => setThemePreference("system"),
  },
];

export interface AppProps {
  readonly client: LeonAidApiClient;
}

function RedirectToOperationalApp() {
  useEffect(() => {
    window.location.replace("/app/");
  }, []);

  return (
    <main className="ui-main">
      <div aria-live="polite" className="action-loading" role="status">
        <span aria-hidden="true" />
        <h1>Akquise-App wird geöffnet</h1>
        <p>Du wirst zu deinem persönlichen Arbeitsbereich weitergeleitet.</p>
      </div>
    </main>
  );
}

/**
 * The current page for another campaign: a campaign's own management page
 * switches to the other campaign, every other page keeps its path and gets
 * the campaign as `?action=` (pages read it when they load).
 */
function campaignHref(actionId: string): string {
  const url = new URL(window.location.href);
  if (/^\/admin\/actions\/[0-9a-f-]{36}\/?$/.test(url.pathname)) {
    return `/admin/actions/${actionId}`;
  }
  url.searchParams.set("action", actionId);
  return `${url.pathname}${url.search}`;
}

function route(available: readonly UiModule[]) {
  const pathname =
    window.location.pathname.replace(/^\/admin/, "").replace(/\/+$/, "") || "/";
  const moduleRoute = resolveModuleRoute(available, "web", pathname);
  if (moduleRoute) return { kind: "module", ...moduleRoute } as const;
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
  const selectedActionId = useCurrentActionId();
  const palette = useCommandPalette();
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
            <a
              className={buttonClassName({ variant: "primary" })}
              href="/login"
            >
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

  // Core lists a module in the navigation only while it is switched on for
  // this installation and allowed for this account.
  const availableModules = webModules.filter((module) =>
    identity.data.navigation.some((item) => item.key === module.id),
  );

  // Module navigation alone does not grant access to the back office.
  if (
    route(availableModules).kind !== "module" &&
    !identity.data.navigation.some(
      (item) =>
        item.surface === "web" &&
        !webModules.some((module) => module.id === item.key),
    )
  ) {
    return <RedirectToOperationalApp />;
  }

  const currentRoute = route(availableModules);
  const actionId =
    currentRoute.kind === "manage"
      ? currentRoute.actionId
      : ["dashboard", "acquisition", "orders", "invoices"].includes(
            currentRoute.kind,
          )
        ? selectedActionId
        : "";
  const editorHref = campaignEditorHref(identity.data, actionId);
  const serverNavigation = identity.data.navigation.map((item) =>
    item.key === "microsite" && editorHref
      ? { ...item, href: editorHref }
      : item,
  );
  const navigation = railNavigation(
    serverNavigation,
    webModules.map((module) => module.id),
  );
  const campaigns = railCampaigns(identity.data);
  const currentCampaignId =
    campaigns.find((campaign) => campaign.id === (actionId || selectedActionId))
      ?.id ??
    identity.data.actionMemberships.find(
      (membership) => membership.role === "charity_admin",
    )?.actionId ??
    campaigns[0]?.id ??
    "";

  return (
    <FeatureFlagProvider client={client} identity={identity.data} surface="web">
      <RailShell
        activeKey={activeNavigationKey(navigation, window.location.pathname)}
        campaignSwitcher={
          campaigns.length > 0
            ? {
                campaigns,
                currentId: currentCampaignId,
                onSelect: (id) => window.location.assign(campaignHref(id)),
              }
            : undefined
        }
        navigation={navigation}
        onOpenPalette={() => palette.setOpen(true)}
        palette={
          <CommandPalette
            commands={themeCommands}
            context={{ client, identity: identity.data }}
            modules={webModules}
            navigation={serverNavigation}
            surface="web"
          />
        }
        onLogout={() => {
          void client.logout().finally(() => {
            window.location.assign("/login");
          });
        }}
        user={{
          name: identity.data.displayName,
          role: identity.data.roleLabels.join(" · "),
        }}
      >
        <div className="page">
          <PreviewNotice />
          {currentRoute.kind === "module" ? (
            currentRoute.render({ client, identity: identity.data })
          ) : currentRoute.kind === "new" ? (
            <CreateActionPage client={client} />
          ) : currentRoute.kind === "manage" ? (
            <ManageActionPage
              actionId={currentRoute.actionId}
              client={client}
              key={currentRoute.actionId}
            />
          ) : currentRoute.kind === "members" ? (
            <MemberAdministrationPage
              client={client}
              identity={identity.data}
            />
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
        </div>
      </RailShell>
    </FeatureFlagProvider>
  );
}
