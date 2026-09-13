import type { ReactNode } from "react";
import type {
  CurrentIdentityResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";

export interface ModulePageContext {
  client: LeonAidApiClient;
  identity: CurrentIdentityResponse;
}

export interface UiModule {
  readonly id: string;
  readonly area: string;
  readonly surfaces: readonly ("web" | "pwa")[];
  readonly routes: readonly {
    readonly pattern: RegExp;
    readonly render: (
      context: ModulePageContext,
      match: RegExpMatchArray,
    ) => ReactNode;
  }[];
}

export function validateUiModules(modules: readonly UiModule[]): void {
  const ids = new Set<string>();
  const routes = new Set<string>();
  for (const module of modules) {
    if (!/^[a-z][a-z0-9-]*$/.test(module.id) || ids.has(module.id)) {
      throw new Error(`Invalid or duplicate UI module: ${module.id}`);
    }
    ids.add(module.id);
    for (const route of module.routes) {
      if (route.pattern.global || route.pattern.sticky) {
        throw new Error(`Stateful route pattern: ${module.id}`);
      }
      for (const surface of module.surfaces) {
        const key = `${surface}:${route.pattern}`;
        if (routes.has(key))
          throw new Error(`Duplicate UI module route: ${key}`);
        routes.add(key);
      }
    }
  }
}

export function resolveModuleRoute(
  modules: readonly UiModule[],
  surface: "web" | "pwa",
  pathname: string,
) {
  const matches = modules.flatMap((module) =>
    module.surfaces.includes(surface)
      ? module.routes.flatMap((route) => {
          const match = pathname.match(route.pattern);
          return match
            ? [
                {
                  moduleId: module.id,
                  render: (context: ModulePageContext) =>
                    route.render(context, match),
                },
              ]
            : [];
        })
      : [],
  );
  if (matches.length > 1)
    throw new Error(`Ambiguous module route: ${pathname}`);
  return matches[0] ?? null;
}
