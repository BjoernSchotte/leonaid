import { useQuery } from "@tanstack/react-query";
import { useEffect, useLayoutEffect, useState, type ReactNode } from "react";

import { ApiError, type LeonAidApiClient } from "@leonaid/api-client";
import {
  ActionListPage,
  AcquisitionAdminPage,
  ActivityFeedPage,
  CommandPalette,
  CommitmentAdminPage,
  DeliveryBoardPage,
  CreateActionPage,
  FeatureFlagProvider,
  InvoiceAdminPage,
  LegalConfigurationPage,
  ManageActionPage,
  MemberAdministrationPage,
  PreviewNotice,
  RoleDashboardPage,
  SystemPage,
  UiSystemCatalogPage,
  useCurrentActionId,
  useLocationHref,
  campaignEditorHref,
  CAMPAIGN_SCOPED_NAV_KEYS,
  openCommandPalette,
  railCampaigns,
  railNavigation,
  readStoredCampaign,
  replaceActionInUrl,
  resolveModuleRoute,
  selectCampaign,
  storeCampaign,
  withCampaign,
  withCrossSurfaceLinks,
  type PaletteCommand,
  type UiModule,
} from "@leonaid/features";
import { ArrowLeftRight, Moon, Sun } from "lucide-react";

import {
  activeNavigationKey,
  Button,
  buttonClassName,
  openCampaignSwitcher,
  RailShell,
  setThemePreference,
  StatusMessage,
  toggleTheme,
} from "@leonaid/ui";

import { webModules } from "./modules";

/** Opens the rail's campaign switcher (also collapsed and on phones). */
const campaignCommand: PaletteCommand = {
  id: "campaign-switch",
  label: "Aktion wechseln …",
  group: "Einstellungen",
  icon: ArrowLeftRight,
  keywords: ["Aktion", "Kampagne", "wechseln", "auswählen"],
  run: openCampaignSwitcher,
};

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

/** Routes whose pages read their campaign from `?action=` when they load. */
const CAMPAIGN_SCOPED_ROUTES: ReadonlySet<string> = new Set([
  "dashboard",
  "acquisition",
  "orders",
  "invoices",
  "delivery",
]);

function urlCampaign(): string {
  return new URLSearchParams(window.location.search).get("action") ?? "";
}

/**
 * A campaign-scoped page opened without `?action=` gets the rail's campaign
 * before it mounts, so it reads the same one. The page waits one layout
 * pass: the URL is set in a layout effect, which runs before the browser
 * paints, so nothing flickers.
 */
function CampaignUrlGate({
  actionId,
  children,
}: {
  readonly actionId: string;
  readonly children: ReactNode;
}) {
  const [ready, setReady] = useState(!actionId);
  useLayoutEffect(() => {
    if (!actionId) return;
    replaceActionInUrl(actionId);
    setReady(true);
  }, [actionId]);
  return ready ? children : null;
}

function route(available: readonly UiModule[]) {
  const pathname =
    window.location.pathname.replace(/^\/admin/, "").replace(/\/+$/, "") || "/";
  const moduleRoute = resolveModuleRoute(available, "web", pathname);
  if (moduleRoute) return { kind: "module", ...moduleRoute } as const;
  if (pathname === "/") return { kind: "dashboard" } as const;
  if (pathname === "/actions") return { kind: "list" } as const;
  if (/^\/members(\/invitations)?$/.test(pathname)) {
    return { kind: "members" } as const;
  }
  if (/^\/(system(\/(jobs|flags))?|privacy)$/.test(pathname)) {
    return { kind: "system" } as const;
  }
  if (/^\/legal(\/[a-z-]+)?$/.test(pathname)) {
    return { kind: "legal" } as const;
  }
  if (pathname === "/system/ui") return { kind: "system-ui" } as const;
  if (pathname === "/orders") return { kind: "orders" } as const;
  if (pathname === "/delivery") return { kind: "delivery" } as const;
  if (/^\/invoices(\/(payments|documents))?$/.test(pathname)) {
    return { kind: "invoices" } as const;
  }
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
  const [storedCampaign, setStoredCampaign] = useState(readStoredCampaign);
  // The campaign the page was opened with; an explicit link counts as choice.
  const [openedWithCampaign] = useState(urlCampaign);
  const identity = useQuery({
    queryFn: () => client.getCurrentIdentity(),
    queryKey: ["identity"],
    retry: (failureCount, error) =>
      !(error instanceof ApiError) && failureCount < 2,
    retryDelay: (attempt) => 150 * (attempt + 1),
    staleTime: 30_000,
  });

  // A link that opened this page with a campaign the admin pages accept
  // counts as the choice for the following pages of this tab.
  useEffect(() => {
    if (
      identity.data &&
      openedWithCampaign &&
      railCampaigns(identity.data).some(
        (campaign) => campaign.id === openedWithCampaign,
      )
    ) {
      storeCampaign(openedWithCampaign);
    }
  }, [identity.data, openedWithCampaign]);
  // In-page tab switches (System ↔ Datenschutz) move the rail highlight.
  useLocationHref();

  if (identity.isPending) {
    return (
      <div aria-live="polite" className="action-loading" role="status">
        <span aria-hidden="true" />
        <h1>Arbeitsbereich wird geladen</h1>
        <p>Ihre Rollen und Charity-Aktionen werden sicher abgerufen.</p>
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
              ? "Ihre Sitzung ist abgelaufen oder Ihr Zugang wurde gesperrt."
              : "LeonAid konnte Ihre Rollen gerade nicht laden. Bitte versuchen Sie es noch einmal."}
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
  const scoped = CAMPAIGN_SCOPED_ROUTES.has(currentRoute.kind);
  const campaigns = railCampaigns(identity.data);
  const usable = (id: string) => campaigns.some((item) => item.id === id);
  const remembered = usable(openedWithCampaign)
    ? openedWithCampaign
    : storedCampaign;
  const currentCampaignId = selectCampaign({
    campaigns,
    scoped,
    managedActionId:
      currentRoute.kind === "manage" ? currentRoute.actionId : undefined,
    urlActionId: selectedActionId,
    storedActionId: remembered,
    fallbackActionId: identity.data.actionMemberships.find(
      (membership) => membership.role === "charity_admin",
    )?.actionId,
  });
  const campaignToCarry = scoped && !selectedActionId ? currentCampaignId : "";
  const actionId =
    currentRoute.kind === "manage" ? currentRoute.actionId : currentCampaignId;
  const editorHref = campaignEditorHref(identity.data, actionId);
  // Rail, g keys and palette share these hrefs: campaign-scoped areas carry
  // the selected campaign, so it holds across navigation.
  const shellNavigation = withCrossSurfaceLinks(identity.data.navigation).map(
    (item) =>
      item.key === "microsite" && editorHref
        ? { ...item, href: editorHref }
        : item.surface === "web" && CAMPAIGN_SCOPED_NAV_KEYS.has(item.key)
          ? { ...item, href: withCampaign(item.href, currentCampaignId) }
          : item,
  );
  const navigation = railNavigation(
    shellNavigation,
    webModules.map((module) => module.id),
  );
  const selectCampaignFromRail = (id: string) => {
    storeCampaign(id);
    setStoredCampaign(id);
    if (currentRoute.kind === "manage") {
      window.location.assign(`/admin/actions/${id}`);
    } else if (scoped) {
      window.location.assign(withCampaign(window.location.pathname, id));
    }
    // Other pages do not depend on the campaign: the rail and its links
    // follow the choice without a reload.
  };

  return (
    <FeatureFlagProvider client={client} identity={identity.data} surface="web">
      <RailShell
        activeKey={activeNavigationKey(navigation, window.location.pathname)}
        campaignSwitcher={
          campaigns.length > 0
            ? {
                campaigns,
                currentId: currentCampaignId,
                onSelect: selectCampaignFromRail,
              }
            : undefined
        }
        navigation={navigation}
        onOpenPalette={openCommandPalette}
        organizationName={identity.data.installation.clubName}
        palette={
          <CommandPalette
            commands={
              campaigns.length > 0
                ? [campaignCommand, ...themeCommands]
                : themeCommands
            }
            context={{ client, identity: identity.data }}
            modules={webModules}
            navigation={shellNavigation}
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
          <CampaignUrlGate actionId={campaignToCarry}>
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
            ) : currentRoute.kind === "delivery" ? (
              <DeliveryBoardPage
                actionId={selectedActionId}
                client={client}
                surface="web"
              />
            ) : currentRoute.kind === "invoices" ? (
              <InvoiceAdminPage client={client} identity={identity.data} />
            ) : currentRoute.kind === "activities" ? (
              <ActivityFeedPage client={client} surface="web" />
            ) : currentRoute.kind === "acquisition" ? (
              <AcquisitionAdminPage client={client} identity={identity.data} />
            ) : currentRoute.kind === "system" ? (
              <SystemPage client={client} identity={identity.data} />
            ) : currentRoute.kind === "legal" ? (
              <LegalConfigurationPage
                client={client}
                identity={identity.data}
              />
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
          </CampaignUrlGate>
        </div>
      </RailShell>
    </FeatureFlagProvider>
  );
}
