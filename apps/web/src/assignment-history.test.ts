import { describe, expect, it } from "vitest";

import { historyText } from "../../../packages/features/src/acquisition/assignment-detail";

const state = (values: Record<string, unknown> = {}) => ({
  acquirerUserId: "10000000-0000-4000-8000-000000000004",
  dueAt: null,
  nextAction: null,
  priority: 0,
  status: "open",
  ...values,
});

describe("assignment history in words", () => {
  it("names the creation", () => {
    expect(historyText({ newState: state(), previousState: {} })).toBe(
      "Zuordnung angelegt",
    );
    expect(
      historyText({
        newState: state({ status: "contacted" }),
        previousState: {},
      }),
    ).toBe("Zuordnung angelegt (Kontaktiert)");
  });

  it("names a status change before anything else", () => {
    expect(
      historyText({
        newState: state({ nextAction: "Anrufen", status: "contacted" }),
        previousState: state(),
      }),
    ).toBe("Status: Offen → Kontaktiert");
    expect(
      historyText({
        newState: state(),
        previousState: state({ status: "handed_over" }),
      }),
    ).toBe("Zuordnung wieder aufgenommen (Offen)");
  });

  it("names the next step and the due day", () => {
    expect(
      historyText({
        newState: state({ nextAction: "Angebot senden" }),
        previousState: state(),
      }),
    ).toBe("Nächster Schritt: Angebot senden");
    expect(
      historyText({
        newState: state(),
        previousState: state({ nextAction: "Angebot senden" }),
      }),
    ).toBe("Nächsten Schritt entfernt");
    expect(
      historyText({
        newState: state({ dueAt: "2026-12-05T09:00:00+00:00" }),
        previousState: state(),
      }),
    ).toBe("Fällig am 05.12.2026");
    expect(
      historyText({
        newState: state(),
        previousState: state({ dueAt: "2026-12-05T09:00:00+00:00" }),
      }),
    ).toBe("Termin entfernt");
  });

  it("falls back for a priority change and unknown states", () => {
    expect(
      historyText({
        newState: state({ priority: 2 }),
        previousState: state(),
      }),
    ).toBe("Priorität geändert");
    expect(historyText({ newState: state(), previousState: state() })).toBe(
      "Zuordnung geändert",
    );
  });
});
