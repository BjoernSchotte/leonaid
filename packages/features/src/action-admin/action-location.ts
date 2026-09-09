import { useEffect, useSyncExternalStore } from "react";

const actionChanged = "leonaid:action-changed";

function subscribe(listener: () => void) {
  window.addEventListener(actionChanged, listener);
  window.addEventListener("popstate", listener);
  return () => {
    window.removeEventListener(actionChanged, listener);
    window.removeEventListener("popstate", listener);
  };
}

export function useCurrentActionId() {
  return useSyncExternalStore(
    subscribe,
    () => new URLSearchParams(window.location.search).get("action") ?? "",
    () => "",
  );
}

// The page owns its validated selection; publish it to the existing URL and
// shell after both initial loading and selector changes, without adding history.
export function useActionInUrl(actionId: string) {
  useEffect(() => {
    if (!actionId) return;
    const url = new URL(window.location.href);
    if (url.searchParams.get("action") === actionId) return;
    url.searchParams.set("action", actionId);
    window.history.replaceState(window.history.state, "", url);
    window.dispatchEvent(new Event(actionChanged));
  }, [actionId]);
}
