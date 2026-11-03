// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { useState } from "react";
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { installDialogPolyfill } from "../test-utils/dialog-polyfill";
import { Modal } from "./modal";
import { ToastProvider, useToast, type LeonAidToast } from "./toast";

beforeAll(installDialogPolyfill);

let show: (toast: LeonAidToast) => string = () => "";
let setModalOpen: (open: boolean) => void = () => undefined;
let setModalMounted: (mounted: boolean) => void = () => undefined;

function Page() {
  show = useToast().show;
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(true);
  setModalOpen = setOpen;
  setModalMounted = setMounted;
  return (
    <>
      <button type="button">Seite</button>
      {mounted ? (
        <Modal onClose={() => setOpen(false)} open={open} title="Dialog">
          <input aria-label="Grund" />
        </Modal>
      ) : null}
    </>
  );
}

/** New toasts appear one frame after show(). */
function frame() {
  act(() => {
    vi.advanceTimersByTime(20);
  });
}

function regions() {
  const polite = document.querySelector<HTMLElement>(
    '.toaster-region[role="status"]',
  )!;
  const assertive = document.querySelector<HTMLElement>(
    '.toaster-region[aria-live="assertive"]',
  )!;
  return { assertive, polite };
}

function renderPage() {
  render(
    <ToastProvider>
      <Page />
    </ToastProvider>,
  );
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Toast live regions", () => {
  it("keeps both region nodes when a modal closes and shows a toast in one update", () => {
    renderPage();
    const before = regions();
    act(() => setModalOpen(true));
    expect(screen.getByRole("dialog").contains(before.polite)).toBe(true);

    act(() => {
      setModalOpen(false);
      show({ timeout: 0, title: "KT26-0004 storniert." });
      show({ timeout: 0, title: "Versand fehlgeschlagen", tone: "error" });
    });
    // Not yet inserted: the regions first settle outside the closed dialog.
    expect(screen.queryByTestId("toast")).toBeNull();
    frame();

    const after = regions();
    expect(after.polite).toBe(before.polite);
    expect(after.assertive).toBe(before.assertive);
    expect(document.body.contains(after.polite)).toBe(true);
    expect(after.polite.closest("dialog")).toBeNull();
    expect(after.polite.textContent).toBe("KT26-0004 storniert.");
    expect(after.assertive.textContent).toBe("Versand fehlgeschlagen");
  });

  it("keeps both region nodes when the open modal unmounts with a toast", () => {
    renderPage();
    const before = regions();
    act(() => setModalOpen(true));
    act(() => {
      setModalMounted(false);
      show({ timeout: 0, title: "Gespeichert" });
    });
    frame();
    const after = regions();
    expect(after.polite).toBe(before.polite);
    expect(after.polite.isConnected).toBe(true);
    expect(after.polite.textContent).toBe("Gespeichert");
  });

  it("keeps region nodes and the hover pause when a modal opens", () => {
    renderPage();
    const before = regions();
    act(() => {
      show({ title: "kurz" });
    });
    frame();
    const toast = screen.getByTestId("toast");
    act(() => {
      toast.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
    });
    act(() => setModalOpen(true));
    expect(regions().polite).toBe(before.polite);
    expect(screen.getByRole("dialog").contains(toast)).toBe(true);
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(screen.getByTestId("toast")).toBe(toast);
  });
});

describe("Toast reach", () => {
  it("renders the toaster inside the open modal so it stays visible and reachable", () => {
    renderPage();
    act(() => setModalOpen(true));
    act(() => {
      show({ timeout: 0, title: "Gespeichert" });
    });
    frame();
    const dialog = screen.getByRole("dialog", { name: "Dialog" });
    expect(dialog.contains(screen.getByTestId("toast"))).toBe(true);

    act(() => setModalOpen(false));
    const toast = screen.getByTestId("toast");
    expect(dialog.contains(toast)).toBe(false);
    expect(toast.textContent).toBe("Gespeichert");
  });

  it("keeps the remaining time when the toaster moves into a modal", () => {
    renderPage();
    act(() => {
      show({ title: "kurz" });
    });
    frame();
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
    renderPage();
    act(() => {
      show({ title: "alt" });
      show({
        action: { label: "Rückgängig", run: () => undefined },
        title: "neu",
      });
    });
    frame();
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
    let hidden = false;
    vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
    renderPage();
    act(() => {
      show({ title: "kurz" });
    });
    frame();
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
