import { ApiError } from "@leonaid/api-client";

export interface ActionErrorMessage {
  readonly code: string | null;
  readonly conflict: boolean;
  readonly message: string;
  readonly requestId: string | null;
}

function withSupportCode(message: string, requestId: string) {
  return `${message} Falls du Unterstützung brauchst, nenne den Support-Code ${requestId}.`;
}

export function actionErrorMessage(error: unknown): ActionErrorMessage {
  if (!(error instanceof ApiError)) {
    return {
      code: null,
      conflict: false,
      message:
        "Die Änderung konnte gerade nicht gespeichert werden. Bitte versuche es erneut.",
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
      message: "Für diese Änderung wird deine Anmeldung erneut bestätigt.",
      requestId: error.detail.requestId,
    };
  }
  if (error.detail.code === "action_revision_conflict") {
    return {
      code: error.detail.code,
      conflict: true,
      message: withSupportCode(
        "Die Aktion wurde zwischenzeitlich von jemand anderem geändert. Deine Eingaben bleiben erhalten. Lade den aktuellen Stand in einem neuen Tab und gleiche die Änderungen ab.",
        error.detail.requestId,
      ),
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
