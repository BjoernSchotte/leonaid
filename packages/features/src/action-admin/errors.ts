import { ApiError } from "@leonaid/api-client";

export interface ActionErrorMessage {
  readonly conflict: boolean;
  readonly message: string;
}

export function actionErrorMessage(error: unknown): ActionErrorMessage {
  if (!(error instanceof ApiError)) {
    return {
      conflict: false,
      message:
        "Die Änderung konnte gerade nicht gespeichert werden. Bitte versuche es erneut.",
    };
  }
  if (error.detail.code === "fresh_login_required") {
    const returnTo = encodeURIComponent(
      `${window.location.pathname}${window.location.search}`,
    );
    window.location.assign(`/fresh-login?returnTo=${returnTo}`);
    return {
      conflict: false,
      message: "Für diese Änderung wird deine Anmeldung erneut bestätigt.",
    };
  }
  if (error.detail.code === "action_revision_conflict") {
    return {
      conflict: true,
      message:
        "Die Aktion wurde zwischenzeitlich von jemand anderem geändert. Deine Eingaben bleiben erhalten. Lade den aktuellen Stand in einem neuen Tab und gleiche die Änderungen ab.",
    };
  }
  return {
    conflict: error.status === 409,
    message: error.detail.message,
  };
}
