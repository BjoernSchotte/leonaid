import type {
  NavigationItemResponse,
  SearchResultResponse,
} from "@leonaid/api-client";

import { Flag, UserPlus, type LucideIcon } from "lucide-react";

import type {
  ModulePageContext,
  ModuleSearchResult,
  ModuleSurface,
  UiModule,
} from "../modules";

/** Shortest query that starts a search ("Ab 2 Zeichen"). */
export const MIN_SEARCH_LENGTH = 2;
/** Longest query the core endpoint accepts. */
export const CORE_SEARCH_MAX_LENGTH = 80;
/** Longest query the module list endpoints accept. */
export const MODULE_SEARCH_MAX_LENGTH = 200;
export const SEARCH_DEBOUNCE_MS = 150;
export const CORE_SEARCH_LIMIT = 8;

export type PaletteHitType =
  | SearchResultResponse["type"]
  | ModuleSearchResult["type"];

export interface PaletteSearchHit {
  readonly id: string;
  readonly type: PaletteHitType;
  readonly title: string;
  readonly context: string;
  readonly href: string;
}

export interface PaletteSearchGroup {
  /** "core:<type>" or "module:<module id>". */
  readonly id: string;
  readonly label: string;
  readonly hits: readonly PaletteSearchHit[];
}

export interface PaletteSearchOutcome {
  readonly groups: readonly PaletteSearchGroup[];
  /** Labels of the sources that failed; the others still show. */
  readonly failed: readonly string[];
  /** True when every source failed. */
  readonly allFailed: boolean;
}

const CORE_GROUPS: ReadonlyArray<
  readonly [SearchResultResponse["type"], string]
> = [
  ["action", "Charity-Aktionen"],
  ["order", "Bestellungen"],
  ["invoice", "Rechnungen"],
  ["sponsor", "Sponsoren"],
  ["member", "Mitglieder"],
];

const CORE_SOURCE_LABEL = "Aktionen, Bestellungen, Rechnungen und Mitglieder";

/** Trims and collapses inner whitespace, as the core endpoint does. */
export function normaliseQuery(query: string): string {
  return query.trim().replace(/\s+/g, " ");
}

export function isSearchQuery(query: string): boolean {
  return normaliseQuery(query).length >= MIN_SEARCH_LENGTH;
}

/** The navigation items of this surface, in server order, without duplicates. */
export function surfaceNavigation(
  navigation: readonly NavigationItemResponse[],
  surface: ModuleSurface,
): NavigationItemResponse[] {
  const seen = new Set<string>();
  return navigation.filter((item) => {
    if (item.surface !== surface || seen.has(item.key)) return false;
    seen.add(item.key);
    return true;
  });
}

export interface PaletteCreateEntry {
  readonly id: string;
  readonly label: string;
  readonly icon: LucideIcon;
  readonly href: string;
}

function listed(
  navigation: readonly NavigationItemResponse[],
  key: string,
  surface: ModuleSurface,
): NavigationItemResponse | undefined {
  return navigation.find(
    (item) => item.key === key && item.surface === surface,
  );
}

/**
 * The "Anlegen" group: create pages the account can already reach. Core
 * entries need their area in the server navigation (the target page shows
 * the same create control); module entries need the module to be enabled
 * for the account and surface. The server authorizes the create itself.
 */
export function createEntries(
  modules: readonly UiModule[],
  navigation: readonly NavigationItemResponse[],
  surface: ModuleSurface,
): PaletteCreateEntry[] {
  const entries: PaletteCreateEntry[] = [];
  const actions = surface === "web" && listed(navigation, "actions", surface);
  if (actions) {
    entries.push({
      id: "create:action",
      label: "Aktion anlegen",
      icon: Flag,
      href: "/admin/actions/new",
    });
  }
  for (const module of modules) {
    if (!module.creates?.length || !module.surfaces.includes(surface)) continue;
    if (!listed(navigation, module.id, surface)) continue;
    for (const entry of module.creates) {
      entries.push({
        id: entry.id,
        label: entry.label,
        icon: entry.icon,
        href: entry.href(surface),
      });
    }
  }
  const members = surface === "web" && listed(navigation, "members", surface);
  if (members) {
    entries.push({
      id: "create:member-invitation",
      label: "Mitglied einladen",
      icon: UserPlus,
      href: `${members.href.replace(/\/+$/, "")}?view=invite`,
    });
  }
  return entries;
}

/**
 * Modules whose search provider may run: registered for this surface and
 * listed by the server in this account's navigation. A module that is
 * switched off (LEONAID_DISABLED_MODULES) has no navigation item, so it
 * contributes no search.
 */
export function enabledSearchModules(
  modules: readonly UiModule[],
  navigation: readonly NavigationItemResponse[],
  surface: ModuleSurface,
): UiModule[] {
  return modules.filter(
    (module) =>
      module.search !== undefined &&
      module.surfaces.includes(surface) &&
      navigation.some(
        (item) => item.key === module.id && item.surface === surface,
      ),
  );
}

/**
 * Runs the core search and every enabled module search in parallel. Every
 * result is what the server returned for this account; nothing is added
 * client-side. Rejects with the abort reason when `signal` aborts.
 */
export async function searchPalette(
  context: ModulePageContext,
  modules: readonly UiModule[],
  surface: ModuleSurface,
  query: string,
  signal: AbortSignal,
): Promise<PaletteSearchOutcome> {
  const text = normaliseQuery(query);
  const searchable = enabledSearchModules(
    modules,
    context.identity.navigation,
    surface,
  );
  const core = context.client
    .searchCore(
      {
        q: text.slice(0, CORE_SEARCH_MAX_LENGTH).trim(),
        limit: CORE_SEARCH_LIMIT,
      },
      { signal },
    )
    .then((response): PaletteSearchGroup[] =>
      CORE_GROUPS.map(([type, label]) => ({
        id: `core:${type}`,
        label,
        hits: response.results
          .filter((result) => result.type === type)
          .map((result) => ({ ...result })),
      })).filter((group) => group.hits.length > 0),
    );
  const moduleSearches = searchable.map((module) =>
    module
      .search!.find(
        context,
        text.slice(0, MODULE_SEARCH_MAX_LENGTH),
        surface,
        signal,
      )
      .then((hits): PaletteSearchGroup[] =>
        hits.length
          ? [
              {
                id: `module:${module.id}`,
                label: module.search!.label,
                hits: hits.map((hit) => ({ ...hit })),
              },
            ]
          : [],
      ),
  );
  const labels = [
    CORE_SOURCE_LABEL,
    ...searchable.map((module) => module.search!.label),
  ];
  const settled = await Promise.allSettled([core, ...moduleSearches]);
  if (signal.aborted) throw signal.reason ?? new DOMException("", "AbortError");
  const groups: PaletteSearchGroup[] = [];
  const failed: string[] = [];
  settled.forEach((result, index) => {
    if (result.status === "fulfilled") groups.push(...result.value);
    else failed.push(labels[index]!);
  });
  return { groups, failed, allFailed: failed.length === settled.length };
}
