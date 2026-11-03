import { ApiError } from "@leonaid/api-client";

export interface ActionErrorMessage {
  readonly code: string | null;
  readonly conflict: boolean;
  readonly message: string;
  readonly requestId: string | null;
}

/**
 * How the copy addresses the person: "Sie" in the back office and on public
 * pages, "du" in the acquisition PWA. The caller knows its surface.
 */
export type ErrorAddress = "Sie" | "du";

export interface ActionErrorOptions {
  /** Default "Sie" (back office). */
  readonly address?: ErrorAddress;
}

const copy = {
  Sie: {
    generic:
      "Die Änderung konnte gerade nicht gespeichert werden. Bitte versuchen Sie es erneut.",
    freshLogin: "Für diese Änderung wird Ihre Anmeldung erneut bestätigt.",
    conflict:
      "Die Aktion wurde zwischenzeitlich von jemand anderem geändert. Ihre Eingaben bleiben erhalten. Laden Sie den aktuellen Stand in einem neuen Tab und gleichen Sie die Änderungen ab.",
    support: (requestId: string) =>
      `Falls Sie Unterstützung brauchen, nennen Sie den Support-Code ${requestId}.`,
  },
  du: {
    generic:
      "Die Änderung konnte gerade nicht gespeichert werden. Bitte versuche es erneut.",
    freshLogin: "Für diese Änderung wird deine Anmeldung erneut bestätigt.",
    conflict:
      "Die Aktion wurde zwischenzeitlich von jemand anderem geändert. Deine Eingaben bleiben erhalten. Lade den aktuellen Stand in einem neuen Tab und gleiche die Änderungen ab.",
    support: (requestId: string) =>
      `Falls du Unterstützung brauchst, nenne den Support-Code ${requestId}.`,
  },
} as const;

export function actionErrorMessage(
  error: unknown,
  { address = "Sie" }: ActionErrorOptions = {},
): ActionErrorMessage {
  const text = copy[address];
  const withSupportCode = (message: string, requestId: string) =>
    `${message} ${text.support(requestId)}`;
  if (!(error instanceof ApiError)) {
    return {
      code: null,
      conflict: false,
      message: text.generic,
      requestId: null,
    };
  }
  if (error.detail.code === "fresh_login_required") {
    const returnTo = encodeURIComponent(
      `${window.location.pathname}${window.location.search}`,
    );
    window.location.assign(`/fresh-login?returnTo=${returnTo}`);
    return {
      code: error.detail.code,
      conflict: false,
      message: text.freshLogin,
      requestId: error.detail.requestId,
    };
  }
  if (error.detail.code === "action_revision_conflict") {
    return {
      code: error.detail.code,
      conflict: true,
      message: withSupportCode(text.conflict, error.detail.requestId),
      requestId: error.detail.requestId,
    };
  }
  return {
    code: error.detail.code,
    conflict: error.status === 409,
    message: withSupportCode(error.detail.message, error.detail.requestId),
    requestId: error.detail.requestId,
  };
}
