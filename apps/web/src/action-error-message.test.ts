import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@leonaid/api-client";

import { actionErrorMessage } from "../../../packages/features/src/action-admin/errors";

const failure = (code: string, status = 422) =>
  new ApiError(status, {
    code,
    message: "Die Eingabe ist ungültig.",
    requestId: "req-123",
  });

afterEach(() => {
  vi.restoreAllMocks();
});

describe("actionErrorMessage", () => {
  it("addresses back-office users with Sie by default", () => {
    expect(actionErrorMessage(new Error("offline")).message).toBe(
      "Die Änderung konnte gerade nicht gespeichert werden. Bitte versuchen Sie es erneut.",
    );
    expect(actionErrorMessage(failure("invalid")).message).toBe(
      "Die Eingabe ist ungültig. Falls Sie Unterstützung brauchen, nennen Sie den Support-Code req-123.",
    );
    const conflict = actionErrorMessage(
      failure("action_revision_conflict", 409),
    );
    expect(conflict.conflict).toBe(true);
    expect(conflict.message).toContain("Ihre Eingaben bleiben erhalten.");
    expect(conflict.message).toContain("Laden Sie den aktuellen Stand");
    expect(conflict.message).not.toMatch(/\b(du|deine?|Lade)\b/);
  });

  it("keeps du for the PWA when the caller asks for it", () => {
    const options = { address: "du" } as const;
    expect(actionErrorMessage(new Error("offline"), options).message).toBe(
      "Die Änderung konnte gerade nicht gespeichert werden. Bitte versuche es erneut.",
    );
    expect(actionErrorMessage(failure("invalid"), options).message).toBe(
      "Die Eingabe ist ungültig. Falls du Unterstützung brauchst, nenne den Support-Code req-123.",
    );
    expect(
      actionErrorMessage(failure("action_revision_conflict", 409), options)
        .message,
    ).toContain("Deine Eingaben bleiben erhalten.");
  });

  it("sends a fresh-login request back to the page in both forms of address", () => {
    const assign = vi.fn();
    vi.spyOn(window, "location", "get").mockReturnValue({
      ...window.location,
      assign,
      pathname: "/admin/invoices",
      search: "?action=a",
    } as Location);
    expect(
      actionErrorMessage(failure("fresh_login_required", 403)).message,
    ).toBe("Für diese Änderung wird Ihre Anmeldung erneut bestätigt.");
    expect(
      actionErrorMessage(failure("fresh_login_required", 403), {
        address: "du",
      }).message,
    ).toBe("Für diese Änderung wird deine Anmeldung erneut bestätigt.");
    expect(assign).toHaveBeenCalledWith(
      `/fresh-login?returnTo=${encodeURIComponent("/admin/invoices?action=a")}`,
    );
  });
});
