import { useSyncExternalStore } from "react";

/** Fired after an in-page URL change, so other parts of the page follow. */
const LOCATION_EVENT = "leonaid:locationchange";

/**
 * Changes the URL without a page load (view switches inside one page) and
 * tells `useLocationHref` subscribers, e.g. the PWA's bottom tabs.
 */
export function navigateInPage(
  url: string,
  { replace = false }: { readonly replace?: boolean } = {},
): void {
  if (replace) window.history.replaceState({}, "", url);
  else window.history.pushState({}, "", url);
  window.dispatchEvent(new Event(LOCATION_EVENT));
}

function subscribe(listener: () => void) {
  window.addEventListener("popstate", listener);
  window.addEventListener(LOCATION_EVENT, listener);
  return () => {
    window.removeEventListener("popstate", listener);
    window.removeEventListener(LOCATION_EVENT, listener);
  };
}

/** Path and query of the current URL; re-renders on in-page changes and Back. */
export function useLocationHref(): string {
  return useSyncExternalStore(
    subscribe,
    () => `${window.location.pathname}${window.location.search}`,
    () => "",
  );
}
