import { validateUiModules, type UiModule } from "@leonaid/features";
import { materialsModule } from "@leonaid/features/materials";
import { tasksModule } from "@leonaid/features/tasks";

// Module pages shipped in the mobile shell. Surveys have no PWA page: their
// PWA navigation entry links to the shared web editor.
export const pwaModules: readonly UiModule[] = [tasksModule, materialsModule];
validateUiModules(pwaModules);

// Module navigation keys the PWA renders as links, pages or not.
export const pwaModuleNavigationKeys = [
  "surveys",
  "tasks",
  "materials",
] as const;

export function pwaPath(pathname: string): string {
  const relative =
    pathname === "/app" || pathname.startsWith("/app/")
      ? pathname.slice("/app".length)
      : pathname;
  return relative.replace(/\/+$/, "") || "/";
}
