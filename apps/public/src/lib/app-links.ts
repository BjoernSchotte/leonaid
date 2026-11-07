import type {
  CurrentIdentityResponse,
  NavigationItemResponse,
} from "@leonaid/api-client";
import { adminHref, pwaHref } from "@leonaid/ui/base-paths";

/** Header link from the public site into one of the signed-in apps. */
export interface AppLink {
  readonly key: "admin" | "pwa";
  readonly href: string;
  readonly label: string;
}

const ADMIN_ENTRY_KEY = "overview-web";
const PWA_ENTRY_KEY = "overview-pwa";

/**
 * The apps the server's navigation opens for the signed-in account.
 *
 * Module items (tasks, inbox, …) come for every account in both surfaces and
 * grant neither app (as in apps/web). The server lists the admin entry
 * `overview-web` only for back-office roles. `overview-pwa` comes for every
 * account; role work in the PWA (acquirer, driver, acquisition) is a "pwa"
 * item without a "web" item of the same key.
 */
export function appLinksFor(
  navigation: readonly NavigationItemResponse[],
): AppLink[] {
  const webKeys = new Set(
    navigation.filter((item) => item.surface === "web").map((item) => item.key),
  );
  const adminEntry = navigation.find(
    (item) => item.surface === "web" && item.key === ADMIN_ENTRY_KEY,
  );
  const pwaWork = navigation.some(
    (item) =>
      item.surface === "pwa" &&
      item.key !== PWA_ENTRY_KEY &&
      !webKeys.has(item.key),
  );
  const pwaEntry = navigation.find(
    (item) => item.surface === "pwa" && item.key === PWA_ENTRY_KEY,
  );

  const links: AppLink[] = [];
  if (adminEntry) {
    links.push({
      key: "admin",
      href: localHref(adminEntry.href, adminHref()),
      label: "Zur Verwaltung",
    });
  }
  if (pwaWork) {
    links.push({
      key: "pwa",
      href: localHref(pwaEntry?.href, pwaHref()),
      label: "Zur Akquise-App",
    });
  }
  return links;
}

/** Only same-origin paths become header links. */
function localHref(href: string | undefined, fallback: string): string {
  return href && href.startsWith("/") && !href.startsWith("//")
    ? href
    : fallback;
}

/**
 * Links for the current visitor; none when signed out (401) or when the
 * identity request fails in any way. The public page never depends on it.
 */
export async function loadAppLinks(api: {
  getCurrentIdentity(): Promise<Pick<CurrentIdentityResponse, "navigation">>;
}): Promise<AppLink[]> {
  try {
    const identity = await api.getCurrentIdentity();
    return Array.isArray(identity?.navigation)
      ? appLinksFor(identity.navigation)
      : [];
  } catch {
    return [];
  }
}

/** Fills the header's reserved, hidden container and shows it when needed. */
export function renderAppLinks(
  container: HTMLElement,
  links: readonly AppLink[],
): void {
  const anchors = links.map((link) => {
    const anchor = container.ownerDocument.createElement("a");
    anchor.className = "site-header__app-link";
    anchor.href = link.href;
    anchor.dataset.appLink = link.key;
    anchor.textContent = link.label;
    return anchor;
  });
  container.replaceChildren(...anchors);
  container.hidden = anchors.length === 0;
}

/**
 * The static header link of a public host that is not the admin host
 * (specs/multi-domain): one sign-in link to the admin host's entry. Null on
 * the admin host itself, in a single-host installation and for an admin base
 * URL that is not a plain HTTPS origin.
 */
export function adminHostLink(
  adminBaseUrl: string | undefined,
  requestHost: string,
): { readonly href: string; readonly label: string } | null {
  let admin: URL;
  try {
    admin = new URL(adminBaseUrl?.trim() ?? "");
  } catch {
    return null;
  }
  if (
    admin.protocol !== "https:" ||
    admin.username ||
    admin.password ||
    admin.search ||
    admin.hash ||
    admin.host.toLowerCase() === requestHost.toLowerCase()
  )
    return null;
  return { href: `${admin.origin}/`, label: "Anmelden" };
}
