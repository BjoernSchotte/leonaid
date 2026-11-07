import { useQuery } from "@tanstack/react-query";
import { LayoutGrid } from "lucide-react";
import { useCallback, useMemo } from "react";

import type {
  CurrentIdentityResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import { buttonClassName, Icon, TabPanel, Tabs, useHotkeys } from "@leonaid/ui";

import { useContextCommands } from "../command-palette/store";
import { navigateInPage, useLocationHref } from "../shared/location";
import { FlagsTab } from "./feature-flag-admin";
import { JobsTab, OperationsTab } from "./operations-admin";
import { PrivacyTab } from "./privacy-admin";
import { SiteHostsTab } from "./site-hosts-admin";
import { adminHref } from "@leonaid/ui/base-paths";

export type SystemSection =
  | "operations"
  | "jobs"
  | "flags"
  | "domains"
  | "privacy";

const TABS: readonly { id: SystemSection; label: string; path: string }[] = [
  { id: "operations", label: "Betrieb", path: adminHref("system") },
  { id: "jobs", label: "Hintergrundaufgaben", path: adminHref("system/jobs") },
  { id: "flags", label: "Funktionen", path: adminHref("system/flags") },
  { id: "domains", label: "Domains", path: adminHref("system/domains") },
  // The privacy area keeps its own URL (and rail entry).
  { id: "privacy", label: "Datenschutz", path: adminHref("privacy") },
];

/** `/admin/system[/jobs|/flags|/domains]` or `/admin/privacy`. */
export function systemSection(pathname: string): SystemSection {
  const path = pathname.replace(/\/+$/, "");
  return TABS.find((tab) => tab.path === path)?.id ?? "operations";
}

export interface SystemPageProps {
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
}

/**
 * System (prototype pages/System.tsx): one page with the tabs Betrieb,
 * Hintergrundaufgaben, Funktionen, Domains and Datenschutz. Every command still
 * goes to its server endpoint with the fresh sign-in step-up.
 */
export function SystemPage({ client, identity }: SystemPageProps) {
  const href = useLocationHref();
  const section = systemSection(href.split("?")[0] ?? "");
  const platform = useQuery({
    queryFn: () => client.getPlatformInformation(),
    queryKey: ["platform-information"],
    retry: false,
    staleTime: 300_000,
  });
  // The failed-job count for the tab comes from the same query as Betrieb.
  const overview = useQuery({
    queryFn: () => client.getOperationsOverview(),
    queryKey: ["operations-overview"],
    refetchInterval: 15_000,
    retry: false,
  });

  const go = useCallback((next: SystemSection) => {
    const tab = TABS.find((item) => item.id === next)!;
    if (window.location.pathname !== tab.path) {
      // Like the prototype: a tab switch replaces the entry, so Back
      // leaves the System page instead of walking through its tabs.
      navigateInPage(`${tab.path}${window.location.search}`, {
        replace: true,
      });
    }
  }, []);

  useHotkeys(
    TABS.map((tab, index) => ({
      keys: String(index + 1),
      label: `Reiter ${tab.label}`,
      group: "System",
      run: () => go(tab.id),
    })),
    [go],
  );
  useContextCommands(
    useMemo(
      () =>
        TABS.filter((tab) => tab.id !== section).map((tab) => ({
          id: `system:tab:${tab.id}`,
          label: `System: ${tab.label}`,
          group: "System",
          run: () => go(tab.id),
        })),
      [go, section],
    ),
  );

  const failed = overview.data?.failedJobs.length;

  return (
    <div className="system" data-testid="system-page">
      <header className="page-header">
        <div>
          <div className="page-heading">
            <h1>System</h1>
            <span className="page-count">
              {platform.data
                ? `Version ${platform.data.release} · eine Installation für ${identity.installation.clubName}`
                : `Eine Installation für ${identity.installation.clubName}`}
            </span>
          </div>
        </div>
        <div className="page-actions">
          <a
            className={buttonClassName({ variant: "ghost" })}
            href={adminHref("system/ui")}
          >
            <Icon icon={LayoutGrid} size={16} />
            <span className="btn-label">UI-Basis</span>
          </a>
        </div>
      </header>
      <Tabs
        idPrefix="system"
        items={TABS.map((tab) => ({
          id: tab.id,
          label: tab.label,
          count: tab.id === "jobs" && failed ? failed : undefined,
        }))}
        label="Systembereiche"
        onChange={go}
        value={section}
      />
      <TabPanel className="system-panel" idPrefix="system" tabId={section}>
        {section === "operations" ? (
          <OperationsTab
            client={client}
            onShowJobs={() => go("jobs")}
            overview={overview}
          />
        ) : section === "jobs" ? (
          <JobsTab client={client} overview={overview} />
        ) : section === "flags" ? (
          <FlagsTab client={client} />
        ) : section === "domains" ? (
          <SiteHostsTab client={client} />
        ) : (
          <PrivacyTab client={client} />
        )}
      </TabPanel>
    </div>
  );
}
