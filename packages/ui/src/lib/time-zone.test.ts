import { describe, expect, it } from "vitest";

import { timeZoneHint } from "./time-zone";

describe("timeZoneHint", () => {
  it("names German time in words", () => {
    expect(timeZoneHint("Europe/Berlin")).toBe("nach deutscher Zeit");
  });

  it("keeps the name of any other zone", () => {
    expect(timeZoneHint("Europe/Vienna")).toBe("in der Zeitzone Europe/Vienna");
  });
});
