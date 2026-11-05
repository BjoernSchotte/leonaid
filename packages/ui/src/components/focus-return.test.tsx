// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { installDialogPolyfill } from "../test-utils/dialog-polyfill";
import { ConfirmDialog } from "./confirm-dialog";
import { FOCUS_WATCH_MS } from "./focus-return";

beforeAll(installDialogPolyfill);
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

type Outcome = "remove" | "disable" | "keep" | "late-remove";

/** A list row whose "Widerrufen" button opens a confirm dialog. */
function Screen({
  outcome,
  fallback = true,
}: {
  readonly outcome: Outcome;
  readonly fallback?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [rowPresent, setRowPresent] = useState(true);
  const [busy, setBusy] = useState(false);
  const confirm = () => {
    setOpen(false);
    if (outcome === "remove") setRowPresent(false);
    if (outcome === "disable") setBusy(true);
    if (outcome === "late-remove") {
      window.setTimeout(() => setRowPresent(false), 50);
    }
  };
  return (
    <main>
      <h1>Mitglieder</h1>
      <section data-focus-fallback={fallback ? "" : undefined} tabIndex={-1}>
        <h2>Einladungen</h2>
        {rowPresent ? (
          <button disabled={busy} onClick={() => setOpen(true)} type="button">
            Widerrufen
          </button>
        ) : null}
      </section>
      <ConfirmDialog
        confirmLabel="Einladung widerrufen"
        description="Der Code wird ungültig."
        onConfirm={confirm}
        onOpenChange={setOpen}
        open={open}
        title="Einladung widerrufen?"
      />
    </main>
  );
}

async function confirmFrom(outcome: Outcome, fallback = true) {
  const user = userEvent.setup();
  render(<Screen fallback={fallback} outcome={outcome} />);
  await user.click(screen.getByRole("button", { name: "Widerrufen" }));
  await user.click(
    screen.getByRole("button", { name: "Einladung widerrufen" }),
  );
}

describe("focus after a confirm dialog", () => {
  it("returns to the opener when it still exists", async () => {
    await confirmFrom("keep");
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Widerrufen" }),
    );
  });

  it("moves to the nearest data-focus-fallback when the opener is removed", async () => {
    await confirmFrom("remove");
    expect(document.activeElement).toBe(
      screen.getByRole("heading", { name: "Einladungen" }).parentElement,
    );
  });

  it("moves to the fallback when the opener is disabled", async () => {
    await confirmFrom("disable");
    expect(document.activeElement?.hasAttribute("data-focus-fallback")).toBe(
      true,
    );
  });

  it("uses the page's main heading without a marked fallback", async () => {
    await confirmFrom("remove", false);
    const heading = screen.getByRole("heading", { level: 1 });
    expect(document.activeElement).toBe(heading);
    expect(heading.tabIndex).toBe(-1);
  });

  it("follows an opener that disappears after the dialog closed", async () => {
    await confirmFrom("late-remove");
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Widerrufen" }),
    );
    await act(() => new Promise((resolve) => setTimeout(resolve, 100)));
    expect(screen.queryByRole("button", { name: "Widerrufen" })).toBeNull();
    expect(document.activeElement?.hasAttribute("data-focus-fallback")).toBe(
      true,
    );
  });

  it("stops watching once the user moved on", async () => {
    const user = userEvent.setup();
    render(
      <>
        <Screen outcome="late-remove" />
        <button type="button">Weiter</button>
      </>,
    );
    await user.click(screen.getByRole("button", { name: "Widerrufen" }));
    await user.click(
      screen.getByRole("button", { name: "Einladung widerrufen" }),
    );
    screen.getByRole("button", { name: "Weiter" }).focus();
    await act(() => new Promise((resolve) => setTimeout(resolve, 100)));
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Weiter" }),
    );
    expect(FOCUS_WATCH_MS).toBeGreaterThan(100);
  });
});
