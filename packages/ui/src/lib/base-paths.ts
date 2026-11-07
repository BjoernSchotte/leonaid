// Base paths of the two member apps (specs/multi-domain §6.7). Product
// constants, not settings: the Vite `base` is fixed at build time and one
// release image serves every installation. Core reads the same values from
// src/leonaid/platform/base_paths.py; tests/unit/test_base_paths.py keeps
// both files equal.
export const ADMIN_BASE = "/admin/";
export const PWA_BASE = "/app/";

/** A path below the PWA base: `pwaHref("sponsors")` → "/app/sponsors". */
export function pwaHref(rest = ""): string {
  return PWA_BASE + rest.replace(/^\/+/, "");
}

/** A path below the admin base: `adminHref("orders")` → "/admin/orders". */
export function adminHref(rest = ""): string {
  return ADMIN_BASE + rest.replace(/^\/+/, "");
}

/** The base without its trailing slash ("/app"), for prefix checks. */
export function baseRoot(base: string): string {
  return base.replace(/\/+$/, "");
}

/**
 * The sign-in page with the current deep link as `returnTo` (§6.7): after the
 * login the member lands exactly there. The sign-in page accepts only paths
 * below the member apps.
 */
export function loginHref(
  location: Pick<Location, "pathname" | "search">,
): string {
  return `/login?returnTo=${encodeURIComponent(location.pathname + location.search)}`;
}

/** Start-area choice of a member (Core `preferredSurface`). */
export type Surface = "web" | "pwa";

/** One start-area option: a surface, or `null` for the default rule. */
export interface StartAreaChoice {
  readonly surface: Surface | null;
  readonly label: string;
}

const START_AREA_LABELS: Record<Surface, string> = {
  web: "Verwaltung als Startbereich verwenden",
  pwa: "Akquise-App als Startbereich verwenden",
};

/** Label of the option that clears the choice (Core: surface null). */
export const DEFAULT_START_AREA_LABEL = "Standard-Startbereich verwenden";

/**
 * The start-area options one app offers a member with roles in both apps
 * (specs/multi-domain §6.7): this app, while the member does not land here,
 * and the default rule, while the member has made a choice. A member with
 * roles in one app only gets none.
 */
export function startAreaChoices(
  current: Surface,
  identity: {
    readonly landingPath: string;
    readonly preferredSurface?: Surface | null;
  },
  bothApps: boolean,
): StartAreaChoice[] {
  if (!bothApps) return [];
  const base = current === "web" ? ADMIN_BASE : PWA_BASE;
  const choices: StartAreaChoice[] = [];
  if (!identity.landingPath.startsWith(base)) {
    choices.push({ surface: current, label: START_AREA_LABELS[current] });
  }
  if (identity.preferredSurface != null) {
    choices.push({ surface: null, label: DEFAULT_START_AREA_LABEL });
  }
  return choices;
}
