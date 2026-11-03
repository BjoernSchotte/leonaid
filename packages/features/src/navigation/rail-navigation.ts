import { Blocks, type LucideIcon, ShieldCheck } from "lucide-react";

import type {
  CurrentIdentityResponse,
  NavigationItemResponse,
} from "@leonaid/api-client";
import type { RailCampaign, RailNavItem } from "@leonaid/ui";

import {
  navigationZones,
  type NavigationZoneGroup,
  zoneForNavKey,
} from "./zones";

const groupOrder: readonly NavigationZoneGroup[] = [
  "Arbeit",
  "Module",
  "Verwaltung",
  "Weitere Oberflächen",
];

/**
 * Server items without a "g" letter in the approved map. They sit in the
 * named group right after `after`.
 */
const unletteredItems: Readonly<
  Record<
    string,
    {
      readonly icon: LucideIcon;
      readonly group: NavigationZoneGroup;
      readonly after: string;
    }
  >
> = {
  privacy: { icon: ShieldCheck, group: "Verwaltung", after: "legal" },
};

function zoneRank(navKey: string): number {
  const index = navigationZones.findIndex((zone) => zone.navKey === navKey);
  return index === -1 ? Number.POSITIVE_INFINITY : index;
}

/**
 * The rail entries for one surface: exactly the items the server navigation
 * returned for the account, labelled and grouped by the zone map. Items
 * the map does not know (a new module) keep their server label and go to
 * "Module" (registered modules) or "Verwaltung".
 */
export function railNavigation(
  navigation: readonly NavigationItemResponse[],
  moduleIds: readonly string[],
  surface: "web" | "pwa" = "web",
): RailNavItem[] {
  const entries = navigation
    .filter((item) => item.surface === surface)
    .map((item, serverIndex) => {
      const zone = zoneForNavKey(item.key);
      const extra = unletteredItems[item.key];
      const isModule = moduleIds.includes(item.key);
      const group: NavigationZoneGroup =
        zone?.group ?? extra?.group ?? (isModule ? "Module" : "Verwaltung");
      const rank = zone
        ? zoneRank(item.key)
        : extra
          ? zoneRank(extra.after) + 0.5
          : navigationZones.length + serverIndex;
      const railItem: RailNavItem = {
        key: item.key,
        label: zone?.label ?? item.label,
        href: item.href,
        icon: zone?.icon ?? extra?.icon ?? Blocks,
        group,
        goKey: zone?.key,
      };
      return { railItem, groupRank: groupOrder.indexOf(group), rank };
    });
  entries.sort((a, b) => a.groupRank - b.groupRank || a.rank - b.rank);
  return entries.map((entry) => entry.railItem);
}

/** Every campaign the account belongs to, once, with its role labels. */
export function railCampaigns(
  identity: Pick<CurrentIdentityResponse, "actionMemberships">,
): RailCampaign[] {
  const campaigns = new Map<string, { name: string; roles: string[] }>();
  for (const membership of identity.actionMemberships) {
    const entry = campaigns.get(membership.actionId);
    if (entry) {
      if (!entry.roles.includes(membership.roleLabel)) {
        entry.roles.push(membership.roleLabel);
      }
    } else {
      campaigns.set(membership.actionId, {
        name: membership.actionName,
        roles: [membership.roleLabel],
      });
    }
  }
  return [...campaigns.entries()].map(([id, entry]) => ({
    id,
    name: entry.name,
    hint: entry.roles.join(" · "),
  }));
}
