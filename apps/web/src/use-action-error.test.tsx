import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@leonaid/api-client";

import { useActionErrorMessage } from "../../../packages/features/src/action-admin/use-action-error";

afterEach(() => vi.restoreAllMocks());

const failure = (code: string, status = 409) =>
  new ApiError(status, { code, message: "Abgelehnt.", requestId: "req-9" });

describe("useActionErrorMessage", () => {
  it("has the message in the first render of the error", () => {
    const seen: (string | undefined)[] = [];
    const { rerender } = renderHook(
      ({ error }: { error: unknown }) => {
        const message = useActionErrorMessage(error);
        seen.push(message?.message);
        return message;
      },
      { initialProps: { error: null as unknown } },
    );
    rerender({ error: failure("some_conflict") });
    expect(seen.at(-1)).toContain("Abgelehnt.");
    // No render showed an empty or stale text for the new error.
    expect(seen.filter((text) => text === undefined)).toHaveLength(1);
  });

  it("still sends a fresh sign-in to /fresh-login, once", () => {
    const assign = vi.fn();
    vi.spyOn(window, "location", "get").mockReturnValue({
      ...window.location,
      assign,
      pathname: "/admin/members",
      search: "",
    } as Location);
    const error = failure("fresh_login_required", 401);
    const { rerender } = renderHook(() => useActionErrorMessage(error));
    rerender();
    expect(assign).toHaveBeenCalledTimes(1);
    expect(assign).toHaveBeenCalledWith(
      `/fresh-login?returnTo=${encodeURIComponent("/admin/members")}`,
    );
  });
});
