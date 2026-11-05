import { useEffect, useMemo } from "react";

import {
  actionErrorMessage,
  type ActionErrorMessage,
  type ActionErrorOptions,
} from "./errors";

/**
 * The message for a query or mutation error. It is worked out in render, so
 * it is there with the first render of the error; only the /fresh-login
 * redirect runs in an effect (it must not repeat on every render).
 */
export function useActionErrorMessage(
  error: unknown,
  options?: ActionErrorOptions,
): ActionErrorMessage | null {
  const message = useMemo(
    () =>
      error ? actionErrorMessage(error, { ...options, redirect: false }) : null,
    // The options are fixed per call site; the error alone triggers it.
    [error],
  );
  useEffect(() => {
    if (message?.code === "fresh_login_required") {
      actionErrorMessage(error, options);
    }
  }, [error]);
  return message;
}

/**
 * Only a stale revision is a conflict the person can resolve by reloading.
 * Other 409s (last charity admin, unchanged role) are plain refusals.
 */
export function isRevisionConflict(message: ActionErrorMessage): boolean {
  return message.code?.endsWith("_revision_conflict") ?? false;
}

/**
 * The actor's own rights changed while the command ran
 * (`admin_scope_changed`, `role_action_scope_changed`): reloading shows
 * what the account may still do.
 */
export function isScopeChange(message: ActionErrorMessage): boolean {
  return message.code?.endsWith("_scope_changed") ?? false;
}
