import {
  Bell,
  Home,
  LayoutDashboard,
  ListTodo,
  type LucideIcon,
  Plus,
  Truck,
  Users,
} from "lucide-react";

import type { NavigationItemResponse } from "@leonaid/api-client";

import { zoneForNavKey } from "@leonaid/features";
import { pwaHref } from "@leonaid/ui/base-paths";

/** Tab of the acquisition app's bottom bar. */
export interface MobileNavTab {
  readonly key: string;
  readonly label: string;
  readonly href: string;
  readonly icon: LucideIcon;
  readonly primary?: boolean;
  /** Fixed digit of the prototype's slot ("1"–"5"). */
  readonly shortcut: string;
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

export const NEW_SPONSOR_TAB_KEY = "sponsor-new";
/** Follow-ups live in the contact view of the activities page. */
export const FOLLOW_UPS_TAB_KEY = "follow-ups";

interface TabDefinition {
  readonly key: string;
  /** Server navigation key that grants the tab. */
  readonly navKey: string;
  readonly label: string;
  readonly icon: LucideIcon;
  readonly shortcut: string;
  /** Fixed target; otherwise the server href. */
  readonly href?: string;
  readonly primary?: boolean;
  /** Whether the tab is the current one for a path and its query. */
  readonly matches: (
    path: string,
    query: URLSearchParams,
    base: string,
  ) => boolean;
}

const under = (path: string, base: string) =>
  path === base || path.startsWith(`${base}/`);

/*
 * The prototype's five tabs with their fixed keys. "Neu" creates a sponsor
 * (the capture view of the sponsor page), as in the prototype.
 */
const TAB_DEFINITIONS: readonly TabDefinition[] = [
  {
    key: "overview-pwa",
    navKey: "overview-pwa",
    label: "Start",
    icon: Home,
    shortcut: "1",
    matches: (path, _query, base) => path === base,
  },
  {
    key: "sponsors",
    navKey: "sponsors",
    label: "Sponsoren",
    icon: Users,
    shortcut: "2",
    matches: (path, query, base) =>
      under(path, base) && query.get("view") !== "new",
  },
  {
    key: NEW_SPONSOR_TAB_KEY,
    navKey: "sponsors",
    label: "Neu",
    icon: Plus,
    shortcut: "3",
    href: pwaHref("sponsors?view=new"),
    primary: true,
    matches: (path, query, base) =>
      under(path, base) && query.get("view") === "new",
  },
  {
    key: FOLLOW_UPS_TAB_KEY,
    navKey: "activities",
    label: "Wiedervorlagen",
    icon: ListTodo,
    shortcut: "4",
    href: pwaHref("activities?view=contacts"),
    matches: (path, query, base) =>
      under(path, base) && query.get("view") === "contacts",
  },
  {
    key: "activities",
    navKey: "activities",
    label: "Neues",
    icon: Bell,
    shortcut: "5",
    matches: (path, query, base) =>
      under(path, base) && query.get("view") !== "contacts",
  },
];

/*
 * "Tour" for drivers while `delivery.tours` is on: first in the bar
 * (critique-driver P0-2, D19 3a). Its digit is the next free one.
 */
const TOUR_TAB: TabDefinition = {
  key: "delivery",
  navKey: "delivery",
  label: "Tour",
  icon: Truck,
  shortcut: "6",
  matches: (path, _query, base) => under(path, base),
};

const TAB_NAV_KEYS = new Set(TAB_DEFINITIONS.map((tab) => tab.navKey));
const definitionsByKey = new Map(
  [TOUR_TAB, ...TAB_DEFINITIONS].map((tab) => [tab.key, tab]),
);

function pathOf(href: string): string {
  return new URL(href, "https://leonaid.invalid").pathname.replace(/\/+$/, "");
}

/** The area of a sheet entry: its first two path segments ("/app/commitments"). */
function areaOf(href: string): string {
  return pathOf(href).split("/").slice(0, 3).join("/");
}

/** The tab for a location, or null (module pages, orders, unknown paths). */
export function activeMobileTab(
  tabs: readonly MobileNavTab[],
  pathname: string,
  search: string,
): string | null {
  const path = pathname.replace(/\/+$/, "");
  const query = new URLSearchParams(search);
  for (const tab of tabs) {
    const definition = definitionsByKey.get(tab.key);
    if (definition?.matches(path, query, pathOf(tab.href))) return tab.key;
  }
  return null;
}

export interface MobileNavigationOptions {
  /**
   * Flag `delivery.tours`: the delivery entry is the driver's "Meine Tour".
   * null while the flag is loading: the entry waits, so its label never
   * flips from "Auslieferung" to "Meine Tour".
   */
  readonly deliveryTours?: boolean | null;
  /** The user drives in the selected action: with the flag, "Tour" leads. */
  readonly driver?: boolean;
  /**
   * Driving is the user's only role in the selected action: `/app/` opens
   * the tour, so "Start" (the acquirer start page) is left out.
   */
  readonly driverOnly?: boolean;
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
  {
    deliveryTours = false,
    driver = false,
    driverOnly = false,
  }: MobileNavigationOptions = {},
): MobileNavigation {
  const pwa = navigation.filter(
    (item) =>
      item.surface === "pwa" &&
      !(item.key === "delivery" && deliveryTours === null),
  );
  const byKey = new Map(pwa.map((item) => [item.key, item]));
  const tabs: MobileNavTab[] = [];
  const tourTab = deliveryTours === true && (driver || driverOnly);
  const definitions = [
    ...(tourTab ? [TOUR_TAB] : []),
    ...TAB_DEFINITIONS.filter(
      (definition) =>
        !(driverOnly && tourTab && definition.key === "overview-pwa"),
    ),
  ];
  const tabNavKeys = new Set(TAB_NAV_KEYS);
  for (const definition of definitions) {
    const item = byKey.get(definition.navKey);
    if (!item || !implemented.has(item.key)) continue;
    tabNavKeys.add(item.key);
    tabs.push({
      key: definition.key,
      label: definition.label,
      href: definition.href ?? item.href,
      icon: definition.icon,
      primary: definition.primary,
      shortcut: definition.shortcut,
    });
  }
  const path = location.pathname.replace(/\/+$/, "");
  const menu = pwa
    .filter((item) => !tabNavKeys.has(item.key) || !implemented.has(item.key))
    .map((item) => {
      const href = implemented.has(item.key) ? item.href : null;
      return {
        key: item.key,
        label:
          deliveryTours && item.key === "delivery" ? "Meine Tour" : item.label,
        icon: zoneForNavKey(item.key)?.icon ?? LayoutDashboard,
        href,
        current: href !== null && under(path, areaOf(href)),
      };
    });
  return {
    tabs,
    active: activeMobileTab(tabs, location.pathname, location.search),
    menu,
  };
}
