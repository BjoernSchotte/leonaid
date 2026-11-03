import {
  Bell,
  Home,
  LayoutDashboard,
  ListTodo,
  type LucideIcon,
  Plus,
  Users,
} from "lucide-react";

import type { NavigationItemResponse } from "@leonaid/api-client";

import { zoneForNavKey } from "./zones";

/** Tab of the acquisition app's bottom bar. */
export interface MobileNavTab {
  readonly key: string;
  readonly label: string;
  readonly href: string;
  readonly icon: LucideIcon;
  readonly primary?: boolean;
}

/** Further PWA area, shown in the "Mehr" sheet. */
export interface MobileNavMenuItem {
  readonly key: string;
  readonly label: string;
  readonly icon: LucideIcon;
  /** null: the server lists the area, but the PWA has no page for it yet. */
  readonly href: string | null;
  readonly current: boolean;
}

export interface MobileNavigation {
  readonly tabs: readonly MobileNavTab[];
  readonly active: string | null;
  readonly menu: readonly MobileNavMenuItem[];
}

/** Follow-ups live in the contact view of the activities page. */
export const FOLLOW_UPS_TAB_KEY = "follow-ups";
const FOLLOW_UPS_HREF = "/app/activities?view=contacts";

/*
 * The prototype's five tabs (Start, Sponsoren, Neu, Wiedervorlagen, Neues),
 * each backed by the server navigation key that grants it.
 */
const TAB_DEFINITIONS: readonly {
  readonly key: string;
  readonly navKey: string;
  readonly label: string;
  readonly icon: LucideIcon;
  readonly href?: string;
  readonly primary?: boolean;
}[] = [
  { key: "overview-pwa", navKey: "overview-pwa", label: "Start", icon: Home },
  { key: "sponsors", navKey: "sponsors", label: "Sponsoren", icon: Users },
  {
    key: "commitment",
    navKey: "commitment",
    label: "Neu",
    icon: Plus,
    primary: true,
  },
  {
    key: FOLLOW_UPS_TAB_KEY,
    navKey: "activities",
    label: "Wiedervorlagen",
    icon: ListTodo,
    href: FOLLOW_UPS_HREF,
  },
  { key: "activities", navKey: "activities", label: "Neues", icon: Bell },
];

const TAB_NAV_KEYS = new Set(TAB_DEFINITIONS.map((tab) => tab.navKey));

function pathOf(href: string): string {
  return new URL(href, "https://leonaid.invalid").pathname.replace(/\/+$/, "");
}

function startsWithPath(pathname: string, href: string): boolean {
  const base = pathOf(href);
  return pathname === base || pathname.startsWith(`${base}/`);
}

/** The tab for a location, or null (module pages, unknown paths). */
export function activeMobileTab(
  tabs: readonly MobileNavTab[],
  pathname: string,
  search: string,
): string | null {
  const path = pathname.replace(/\/+$/, "") || "/";
  const view = new URLSearchParams(search).get("view");
  for (const tab of tabs) {
    if (tab.key === FOLLOW_UPS_TAB_KEY) {
      if (startsWithPath(path, tab.href) && view === "contacts") return tab.key;
      continue;
    }
    if (tab.key === "activities") {
      if (startsWithPath(path, tab.href) && view !== "contacts") return tab.key;
      continue;
    }
    if (tab.key === "overview-pwa") {
      if (path === pathOf(tab.href)) return tab.key;
      continue;
    }
    if (startsWithPath(path, tab.href)) return tab.key;
  }
  return null;
}

/**
 * Splits the PWA entries of the server navigation into bottom tabs and the
 * "Mehr" sheet. Only entries the server returned appear; `implemented` names
 * the keys the PWA has pages or links for, the rest show as "In Aufbau".
 */
export function mobileNavigation(
  navigation: readonly NavigationItemResponse[],
  implemented: ReadonlySet<string>,
  location: { readonly pathname: string; readonly search: string },
): MobileNavigation {
  const pwa = navigation.filter((item) => item.surface === "pwa");
  const byKey = new Map(pwa.map((item) => [item.key, item]));
  const tabs: MobileNavTab[] = [];
  for (const definition of TAB_DEFINITIONS) {
    const item = byKey.get(definition.navKey);
    if (!item || !implemented.has(item.key)) continue;
    tabs.push({
      key: definition.key,
      label: definition.label,
      href: definition.href ?? item.href,
      icon: definition.icon,
      primary: definition.primary,
    });
  }
  const path = location.pathname.replace(/\/+$/, "") || "/";
  const menu = pwa
    .filter((item) => !TAB_NAV_KEYS.has(item.key) || !implemented.has(item.key))
    .map((item) => {
      const href = implemented.has(item.key) ? item.href : null;
      return {
        key: item.key,
        label: item.label,
        icon: zoneForNavKey(item.key)?.icon ?? LayoutDashboard,
        href,
        current: href !== null && startsWithPath(path, href),
      };
    });
  return {
    tabs,
    active: activeMobileTab(tabs, location.pathname, location.search),
    menu,
  };
}
