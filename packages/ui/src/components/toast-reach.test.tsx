// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { installDialogPolyfill } from "../test-utils/dialog-polyfill";
import { Modal } from "./modal";
import { ToastProvider, useToast, type LeonAidToast } from "./toast";

beforeAll(installDialogPolyfill);

let show: (toast: LeonAidToast) => string = () => "";
let setModalOpen: (open: boolean) => void = () => undefined;

function Page() {
  show = useToast().show;
  const [open, setOpen] = useState(false);
  setModalOpen = setOpen;
  return (
    <>
      <button type="button">Seite</button>
      <Modal onClose={() => setOpen(false)} open={open} title="Dialog">
        <input aria-label="Grund" />
      </Modal>
    </>
  );
}

function renderPage() {
  render(
    <ToastProvider>
      <Page />
    </ToastProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Toast reach", () => {
  it("renders the toaster inside the open modal so it stays visible and reachable", () => {
    renderPage();
    act(() => setModalOpen(true));
    act(() => {
      show({ timeout: 0, title: "Gespeichert" });
    });
    const dialog = screen.getByRole("dialog", { name: "Dialog" });
    expect(dialog.contains(screen.getByTestId("toast"))).toBe(true);

    act(() => setModalOpen(false));
    const toast = screen.getByTestId("toast");
    expect(dialog.contains(toast)).toBe(false);
    expect(toast.textContent).toBe("Gespeichert");
  });

  it("keeps the remaining time when the toaster moves into a modal", () => {
    vi.useFakeTimers();
    renderPage();
    act(() => {
      show({ title: "kurz" });
    });
    act(() => {
      vi.advanceTimersByTime(4_000);
    });
    act(() => setModalOpen(true));
    act(() => {
      vi.advanceTimersByTime(1_200);
    });
    expect(screen.queryByTestId("toast")).toBeNull();
  });

  it("jumps to the newest toast with F6 and pauses it there", () => {
    vi.useFakeTimers();
    renderPage();
    act(() => {
      show({ title: "alt" });
      show({
        action: { label: "Rückgängig", run: () => undefined },
        title: "neu",
      });
    });
    screen.getByRole("button", { name: "Seite" }).focus();
    fireEvent.keyDown(document, { key: "F6" });
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Rückgängig" }),
    );
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(screen.getAllByTestId("toast").map((t) => t.textContent)).toContain(
      "neuRückgängig",
    );
  });

  it("leaves F6 alone without toasts", () => {
    renderPage();
    const event = new KeyboardEvent("keydown", {
      bubbles: true,
      cancelable: true,
      key: "F6",
    });
    document.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
  });

  it("pauses timers while the page is hidden", () => {
    vi.useFakeTimers();
    let hidden = false;
    vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
    renderPage();
    act(() => {
      show({ title: "kurz" });
    });
    act(() => {
      vi.advanceTimersByTime(2_000);
      hidden = true;
      document.dispatchEvent(new Event("visibilitychange"));
    });
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(screen.getByTestId("toast")).toBeTruthy();
    act(() => {
      hidden = false;
      document.dispatchEvent(new Event("visibilitychange"));
    });
    act(() => {
      vi.advanceTimersByTime(3_200);
    });
    expect(screen.queryByTestId("toast")).toBeNull();
  });
});
