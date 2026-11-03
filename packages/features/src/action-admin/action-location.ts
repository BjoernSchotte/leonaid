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

const ACTION_ID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * The `?action=` id when it is well formed, not one of `options` and the
 * account holds a role that reads every action (system admin, global
 * finance). Search links carry such ids for actions without a membership.
 * The server still authorizes every request for it.
 */
export function requestedUnlistedAction(
  options: readonly { readonly actionId: string }[],
  mayReadEveryAction: boolean,
  search: string = window.location.search,
): string | null {
  if (!mayReadEveryAction) return null;
  const requested = new URLSearchParams(search).get("action");
  if (!requested || !ACTION_ID.test(requested)) return null;
  return options.some((option) => option.actionId === requested)
    ? null
    : requested;
}
