import { useEffect, useState } from "react";

import {
  actionErrorMessage,
  type ActionErrorMessage,
  type ActionErrorOptions,
} from "./errors";

/**
 * The message for a query or mutation error, worked out once per error.
 * actionErrorMessage redirects to /fresh-login, so it must not run in
 * render (it would assign the location on every render).
 */
export function useActionErrorMessage(
  error: unknown,
  options?: ActionErrorOptions,
): ActionErrorMessage | null {
  const [message, setMessage] = useState<ActionErrorMessage | null>(null);
  useEffect(() => {
    setMessage(error ? actionErrorMessage(error, options) : null);
    // The options are fixed per call site; the error alone triggers it.
  }, [error]);
  return error ? message : null;
}

/**
 * Only a stale revision is a conflict the person can resolve by reloading.
 * Other 409s (last charity admin, unchanged role) are plain refusals.
 */
export function isRevisionConflict(message: ActionErrorMessage): boolean {
  return message.code?.endsWith("_revision_conflict") ?? false;
}
