import { Dialog } from "@base-ui/react/dialog";
import {
  Activity01Icon,
  AddressBookIcon,
  Cancel01Icon,
  CharityIcon,
  DashboardSquare01Icon,
  Invoice03Icon,
  Logout01Icon,
  Menu01Icon,
  Settings02Icon,
  SidebarLeftIcon,
  UserGroupIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useState, type ReactNode } from "react";

import type {
  CurrentIdentityResponse,
  NavigationItemResponse,
} from "@leonaid/api-client";

import { cn } from "../lib/utils";
import { Button } from "./button";
import { ThemeSwitcher } from "./theme-switcher";

export interface AppShellProps {
  readonly children: ReactNode;
  readonly currentActionName: string;
  readonly identity: CurrentIdentityResponse;
  readonly onLogout: () => void;
  readonly surface?: "pwa" | "web";
}

const navigationIcons = {
  actions: CharityIcon,
  activities: Activity01Icon,
  invoices: Invoice03Icon,
  members: UserGroupIcon,
  "overview-pwa": DashboardSquare01Icon,
  "overview-web": DashboardSquare01Icon,
  sponsors: AddressBookIcon,
  system: Settings02Icon,
} as const;

const implementedWebNavigation = new Set(["actions", "members"]);
const implementedPwaNavigation = new Set([
  "activities",
  "overview-pwa",
  "sponsors",
]);

function iconFor(item: NavigationItemResponse) {
  return (
    navigationIcons[item.key as keyof typeof navigationIcons] ??
    DashboardSquare01Icon
  );
}

function isCurrent(item: NavigationItemResponse): boolean {
  const pathname = window.location.pathname;
  return item.href.endsWith("/")
    ? pathname === item.href
    : pathname.startsWith(item.href);
}

function Navigation({
  collapsed = false,
  implemented,
  items,
  onNavigate,
}: {
  readonly collapsed?: boolean;
  readonly implemented: ReadonlySet<string>;
  readonly items: ReadonlyArray<NavigationItemResponse>;
  readonly onNavigate?: () => void;
}) {
  return (
    <nav aria-label="Hauptnavigation" className="ui-nav">
      {items.map((item) =>
        implemented.has(item.key) ? (
          <a
            aria-current={isCurrent(item) ? "page" : undefined}
            className="ui-nav__item"
            data-nav-key={item.key}
            href={item.href}
            key={`${item.surface}-${item.key}`}
            onClick={onNavigate}
            title={collapsed ? item.label : undefined}
          >
            <HugeiconsIcon
              aria-hidden="true"
              icon={iconFor(item)}
              size={20}
              strokeWidth={1.7}
            />
            <span>{item.label}</span>
          </a>
        ) : (
          <span
            aria-disabled="true"
            className="ui-nav__item ui-nav__item--disabled"
            data-nav-key={item.key}
            key={`${item.surface}-${item.key}`}
            title={collapsed ? `${item.label} – in Aufbau` : undefined}
          >
            <HugeiconsIcon
              aria-hidden="true"
              icon={iconFor(item)}
              size={20}
              strokeWidth={1.7}
            />
            <span>{item.label}</span>
            <small className="ui-nav__status">In Aufbau</small>
          </span>
        ),
      )}
    </nav>
  );
}

export function AppShell({
  children,
  currentActionName,
  identity,
  onLogout,
  surface = "web",
}: AppShellProps) {
  const [collapsed, setCollapsed] = useState(
    () => window.localStorage.getItem("leonaid.sidebar-collapsed") === "true",
  );
  const [mobileOpen, setMobileOpen] = useState(false);
  const navigation = identity.navigation.filter(
    (item) =>
      item.surface === surface &&
      (surface === "pwa" || item.key !== "overview-web"),
  );
  const implemented =
    surface === "pwa" ? implementedPwaNavigation : implementedWebNavigation;

  function toggleSidebar() {
    const next = !collapsed;
    setCollapsed(next);
    window.localStorage.setItem("leonaid.sidebar-collapsed", String(next));
  }

  const sidebarNavigation = (
    <>
      <p className="ui-sidebar__label">Arbeitsbereich</p>
      <Navigation
        collapsed={collapsed}
        implemented={implemented}
        items={navigation}
        onNavigate={() => setMobileOpen(false)}
      />
      <div className="ui-sidebar__context">
        <span>Aktuelle Aktion</span>
        <strong data-testid="current-action">{currentActionName}</strong>
      </div>
    </>
  );

  return (
    <div
      className={cn("ui-shell", collapsed && "ui-shell--collapsed")}
      data-sidebar-collapsed={collapsed}
      data-surface={surface}
    >
      <aside className="ui-sidebar" data-testid="desktop-sidebar">
        <div className="ui-sidebar__header">
          <div className="ui-brand">
            <span aria-hidden="true" className="ui-brand__mark">
              L
            </span>
            <span className="ui-brand__name">LeonAid</span>
          </div>
          <button
            aria-label={collapsed ? "Sidebar ausklappen" : "Sidebar einklappen"}
            className="ui-sidebar__collapse"
            data-testid="sidebar-toggle"
            onClick={toggleSidebar}
            title={collapsed ? "Sidebar ausklappen" : "Sidebar einklappen"}
            type="button"
          >
            <HugeiconsIcon
              aria-hidden="true"
              icon={SidebarLeftIcon}
              size={20}
              strokeWidth={1.7}
            />
          </button>
        </div>
        {sidebarNavigation}
      </aside>

      <div className="ui-shell__body">
        <header className="ui-topbar">
          <Dialog.Root
            onOpenChange={setMobileOpen}
            open={surface === "web" && mobileOpen}
          >
            <Dialog.Trigger
              aria-label="Navigation öffnen"
              className={cn(
                "ui-icon-button ui-mobile-menu",
                surface === "pwa" && "ui-mobile-menu--hidden",
              )}
              data-testid="mobile-menu"
            >
              <HugeiconsIcon
                aria-hidden="true"
                icon={Menu01Icon}
                size={22}
                strokeWidth={1.8}
              />
            </Dialog.Trigger>
            <Dialog.Portal>
              <Dialog.Backdrop className="ui-dialog-backdrop" />
              <Dialog.Popup className="ui-mobile-drawer">
                <Dialog.Title className="sr-only">Navigation</Dialog.Title>
                <Dialog.Description className="sr-only">
                  Bereiche des LeonAid-Arbeitsbereichs
                </Dialog.Description>
                <Dialog.Close
                  aria-label="Navigation schließen"
                  className="ui-icon-button ui-mobile-drawer__close"
                >
                  <HugeiconsIcon
                    aria-hidden="true"
                    icon={Cancel01Icon}
                    size={22}
                    strokeWidth={1.8}
                  />
                </Dialog.Close>
                <div className="ui-brand">
                  <span aria-hidden="true" className="ui-brand__mark">
                    L
                  </span>
                  <span className="ui-brand__name">LeonAid</span>
                </div>
                {sidebarNavigation}
              </Dialog.Popup>
            </Dialog.Portal>
          </Dialog.Root>

          <div className="ui-topbar__identity">
            <span>Angemeldet als</span>
            <strong data-testid="display-name">{identity.displayName}</strong>
          </div>
          <div className="ui-topbar__actions">
            <ThemeSwitcher />
            <div
              aria-label="Rollen"
              className="ui-role-list"
              data-testid="roles"
            >
              {identity.roleLabels.map((label) => (
                <span className="ui-role" key={label}>
                  {label}
                </span>
              ))}
            </div>
            <Button
              aria-label="Abmelden"
              data-testid="logout"
              icon={
                <HugeiconsIcon
                  aria-hidden="true"
                  icon={Logout01Icon}
                  size={18}
                  strokeWidth={1.8}
                />
              }
              onClick={onLogout}
              title="Abmelden"
              variant="ghost"
            >
              Abmelden
            </Button>
          </div>
        </header>
        <main className="ui-main" id="main-content">
          {children}
        </main>
      </div>
      {surface === "pwa" ? (
        <div className="ui-pwa-tabbar">
          <Navigation implemented={implemented} items={navigation} />
        </div>
      ) : null}
    </div>
  );
}
