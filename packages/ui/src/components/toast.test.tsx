// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider, useToast, type LeonAidToast } from "./toast";

let show: (toast: LeonAidToast) => string = () => "";

function Capture() {
  show = useToast().show;
  return null;
}

beforeEach(() => {
  vi.useFakeTimers();
  render(
    <ToastProvider>
      <Capture />
    </ToastProvider>,
  );
});

/** New toasts appear one frame after show(). */
function frame() {
  act(() => {
    vi.advanceTimersByTime(20);
  });
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Toast", () => {
  it("announces info and success toasts in the polite live region", () => {
    const region = screen.getByRole("status");
    expect(region.className).toBe("toaster-region");
    expect(region.parentElement?.className).toBe("toaster");
    expect(region.getAttribute("aria-live")).toBe("polite");

    act(() => {
      show({
        description: "Die Zuordnung wurde aktualisiert.",
        title: "Gespeichert",
        tone: "success",
      });
    });
    frame();
    const toast = screen.getByTestId("toast");
    expect(region.contains(toast)).toBe(true);
    expect(toast.className).toBe("toast tone-ok");
    expect(toast.querySelector(":scope > svg")).not.toBeNull();
    expect(toast.querySelector(".toast-text")?.textContent).toBe(
      "GespeichertDie Zuordnung wurde aktualisiert.",
    );
  });

  it("announces error toasts in an assertive live region without an empty alert role", () => {
    expect(screen.queryByRole("alert")).toBeNull();
    const alert = document.querySelector<HTMLElement>(
      '.toaster-region[aria-live="assertive"]',
    )!;
    act(() => {
      show({ title: "Nicht gespeichert", tone: "error" });
      show({ title: "Hinweis", tone: "info" });
    });
    frame();
    expect(alert.textContent).toBe("Nicht gespeichert");
    expect(screen.getByRole("status").textContent).toBe("Hinweis");
  });

  it.each([
    ["error", "toast tone-danger"],
    ["info", "toast tone-info"],
  ] as const)("maps tone %s to %s", (tone, className) => {
    act(() => {
      show({ title: "x", tone });
    });
    frame();
    expect(screen.getByTestId("toast").className).toBe(className);
  });

  it("closes with Meldung schließen", () => {
    act(() => {
      show({ title: "Gespeichert" });
    });
    frame();
    act(() => {
      screen.getByRole("button", { name: "Meldung schließen" }).click();
    });
    expect(screen.queryByTestId("toast")).toBeNull();
  });

  it("dismisses after 5.2 s, keeps timeout 0 open", () => {
    act(() => {
      show({ title: "kurz" });
      show({ timeout: 0, title: "bleibt" });
    });
    frame();
    act(() => {
      vi.advanceTimersByTime(5_199);
    });
    expect(screen.getAllByTestId("toast")).toHaveLength(2);
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.getAllByTestId("toast").map((t) => t.textContent)).toEqual([
      "bleibt",
    ]);
  });

  it("pauses the timer while hovered", () => {
    act(() => {
      show({ title: "kurz" });
    });
    frame();
    const toast = screen.getByTestId("toast");
    act(() => {
      vi.advanceTimersByTime(3_000);
    });
    act(() => {
      toast.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
    });
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(screen.getByTestId("toast")).toBeTruthy();
    act(() => {
      toast.dispatchEvent(new MouseEvent("mouseout", { bubbles: true }));
    });
    act(() => {
      vi.advanceTimersByTime(2_199);
    });
    expect(screen.getByTestId("toast")).toBeTruthy();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.queryByTestId("toast")).toBeNull();
  });

  it("keeps at most three toasts", () => {
    act(() => {
      for (const title of ["1", "2", "3", "4"]) show({ timeout: 0, title });
    });
    frame();
    expect(screen.getAllByTestId("toast").map((t) => t.textContent)).toEqual([
      "2",
      "3",
      "4",
    ]);
  });

  it("runs an action and dismisses the toast", () => {
    const run = vi.fn();
    act(() => {
      show({ action: { label: "Rückgängig", run }, title: "Bestätigt" });
    });
    frame();
    const action = screen.getByRole("button", { name: "Rückgängig" });
    expect(action.className).toBe("toast-action");
    act(() => {
      action.click();
    });
    expect(run).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("toast")).toBeNull();
  });

  it("returns distinct ids", () => {
    let ids: string[] = [];
    act(() => {
      ids = [show({ title: "a" }), show({ title: "b" })];
    });
    frame();
    expect(new Set(ids).size).toBe(2);
  });
});
