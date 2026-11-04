import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import type {
  CurrentIdentityResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";

export type ModuleSurface = "web" | "pwa";

export interface ModulePageContext {
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
}

export interface ModuleRoute {
  /**
   * Matched against the shell-relative path: the shell strips its base
   * (`/admin` or `/app`) and trailing slashes, so `/admin/surveys/` becomes
   * `/surveys`. The root path is `/`.
   */
  readonly pattern: RegExp;
  readonly render: (
    context: ModulePageContext,
    match: RegExpMatchArray,
    surface: ModuleSurface,
  ) => ReactNode;
}

export interface ModuleSearchResult {
  readonly id: string;
  readonly type: "task" | "knowledge-page" | "material" | "inbox-case";
  readonly title: string;
  readonly context: string;
  readonly href: string;
}

export interface ModuleSearchProvider {
  readonly label: string;
  /** Returns only objects the server lets the current account read. */
  readonly find: (
    context: ModulePageContext,
    query: string,
    surface: ModuleSurface,
    signal: AbortSignal,
  ) => Promise<readonly ModuleSearchResult[]>;
}

/**
 * An "Anlegen" entry in the command palette. The target page reads
 * `?create=<kind>` (see command-palette/create-request.ts) and opens its own
 * create form. Shown only while the module is enabled for the account; the
 * page's create request is still authorized by the server.
 */
export interface ModuleCreateEntry {
  /** "create:<kind>"; a mounted page command with the same id replaces it. */
  readonly id: string;
  readonly label: string;
  readonly icon: LucideIcon;
  readonly href: (surface: ModuleSurface) => string;
}

/**
 * A UI contribution of one backend module. The ID is the backend module ID.
 * Registration only makes pages reachable; the server still authorizes every
 * request and filters navigation, so a registered route grants no access.
 * Navigation items that a module contributes use the module ID as key; the
 * shells use that to tell module entries from back-office entries.
 */
export interface UiModule {
  readonly id: string;
  readonly label: string;
  readonly surfaces: readonly ModuleSurface[];
  readonly routes: readonly ModuleRoute[];
  readonly search?: ModuleSearchProvider;
  readonly creates?: readonly ModuleCreateEntry[];
}

export interface ResolvedModuleRoute {
  readonly moduleId: string;
  readonly label: string;
  readonly render: (context: ModulePageContext) => ReactNode;
}

const MODULE_ID = /^[a-z][a-z0-9-]*$/;

export function validateUiModules(modules: readonly UiModule[]): void {
  const ids = new Set<string>();
  const patterns = new Set<string>();
  for (const module of modules) {
    if (!MODULE_ID.test(module.id) || ids.has(module.id)) {
      throw new Error(`Invalid or duplicate UI module: ${module.id}`);
    }
    ids.add(module.id);
    if (module.surfaces.length === 0) {
      throw new Error(`UI module without surface: ${module.id}`);
    }
    for (const route of module.routes) {
      // Stateful flags make RegExp.match depend on earlier calls.
      if (route.pattern.global || route.pattern.sticky) {
        throw new Error(`Stateful route pattern in UI module: ${module.id}`);
      }
      for (const surface of module.surfaces) {
        const key = `${surface}:${route.pattern.source}:${route.pattern.flags}`;
        if (patterns.has(key)) {
          throw new Error(`Duplicate UI module route: ${key}`);
        }
        patterns.add(key);
      }
    }
  }
}

export function resolveModuleRoute(
  modules: readonly UiModule[],
  surface: ModuleSurface,
  path: string,
): ResolvedModuleRoute | null {
  const matches: ResolvedModuleRoute[] = [];
  for (const module of modules) {
    if (!module.surfaces.includes(surface)) continue;
    for (const route of module.routes) {
      const match = path.match(route.pattern);
      if (match) {
        matches.push({
          moduleId: module.id,
          label: module.label,
          render: (context) => route.render(context, match, surface),
        });
      }
    }
  }
  if (matches.length > 1) {
    throw new Error(`Ambiguous UI module route: ${path}`);
  }
  return matches[0] ?? null;
}
