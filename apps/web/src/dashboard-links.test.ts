import { describe, expect, it } from "vitest";

import { withParam } from "../../../packages/features/src/dashboard/dashboard";

describe("withParam", () => {
  it("adds a parameter to a link with or without a query", () => {
    expect(withParam("/app/sponsors", "status", "open")).toBe(
      "/app/sponsors?status=open",
    );
    expect(withParam("/app/sponsors?action=a1", "status", "open")).toBe(
      "/app/sponsors?action=a1&status=open",
    );
    expect(
      withParam("/app/activities?view=contacts", "urgency", "overdue"),
    ).toBe("/app/activities?view=contacts&urgency=overdue");
  });

  it("replaces a parameter that is already there", () => {
    expect(withParam("/app/sponsors?status=all", "status", "open")).toBe(
      "/app/sponsors?status=open",
    );
  });
});
