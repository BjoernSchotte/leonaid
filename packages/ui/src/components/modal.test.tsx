// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { installDialogPolyfill } from "../test-utils/dialog-polyfill";
import { Modal } from "./modal";

beforeAll(installDialogPolyfill);
afterEach(cleanup);

function Harness({
  mounted = true,
  onClose,
}: {
  readonly mounted?: boolean;
  readonly onClose?: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)} type="button">
        Öffnen
      </button>
      {mounted ? (
        <Modal
          description="Die Rechnung bleibt sichtbar."
          footer={
            <button onClick={() => setOpen(false)} type="button">
              Abbrechen
            </button>
          }
          onClose={() => {
            onClose?.();
            setOpen(false);
          }}
          open={open}
          title="Rechnung stornieren?"
        >
          <input aria-label="Grund" />
        </Modal>
      ) : null}
    </>
  );
}

describe("Modal", () => {
  it("opens with showModal, labels itself and focuses the first control", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Öffnen" }));

    const dialog = screen.getByRole("dialog", { name: "Rechnung stornieren?" });
    expect(dialog).toHaveProperty("open", true);
    expect(dialog.className).toBe("modal modal-md");
    expect(dialog.getAttribute("aria-describedby")).toBe(
      screen.getByText("Die Rechnung bleibt sichtbar.").id,
    );
    expect(document.activeElement).toBe(
      screen.getByRole("textbox", { name: "Grund" }),
    );
  });

  it("returns focus to the opener after Esc", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    const opener = screen.getByRole("button", { name: "Öffnen" });
    await user.click(opener);
    expect(document.activeElement).not.toBe(opener);

    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(document.querySelector("dialog")?.open).toBe(false);
    expect(document.activeElement).toBe(opener);
  });

  it("closes on a backdrop click but not on a click inside", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    await user.click(screen.getByRole("button", { name: "Öffnen" }));

    await user.click(screen.getByRole("textbox", { name: "Grund" }));
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("reports a close the browser forced (second Esc in Chromium)", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    const opener = screen.getByRole("button", { name: "Öffnen" });
    await user.click(opener);

    // The browser may close without a cancelable `cancel` event.
    (document.querySelector("dialog") as HTMLDialogElement).close();

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(opener);
  });

  it("returns focus when the open modal unmounts", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Harness />);
    const opener = screen.getByRole("button", { name: "Öffnen" });
    await user.click(opener);
    rerender(<Harness mounted={false} />);
    expect(document.activeElement).toBe(opener);
  });

  it("locks page scroll while open and restores it on close and unmount", async () => {
    const user = userEvent.setup();
    const root = document.documentElement;
    const { rerender } = render(<Harness />);
    expect(root.classList.contains("modal-open")).toBe(false);

    await user.click(screen.getByRole("button", { name: "Öffnen" }));
    expect(root.classList.contains("modal-open")).toBe(true);
    await user.keyboard("{Escape}");
    expect(root.classList.contains("modal-open")).toBe(false);

    await user.click(screen.getByRole("button", { name: "Öffnen" }));
    rerender(<Harness mounted={false} />);
    expect(root.classList.contains("modal-open")).toBe(false);
  });

  it("keeps the lock until the last of two open modals closes", () => {
    const root = document.documentElement;
    const { rerender } = render(
      <>
        <Modal onClose={() => undefined} open title="Eins" />
        <Modal onClose={() => undefined} open title="Zwei" />
      </>,
    );
    expect(root.classList.contains("modal-open")).toBe(true);
    rerender(
      <>
        <Modal onClose={() => undefined} open title="Eins" />
        <Modal onClose={() => undefined} open={false} title="Zwei" />
      </>,
    );
    expect(root.classList.contains("modal-open")).toBe(true);
    rerender(
      <>
        <Modal onClose={() => undefined} open={false} title="Eins" />
        <Modal onClose={() => undefined} open={false} title="Zwei" />
      </>,
    );
    expect(root.classList.contains("modal-open")).toBe(false);
  });

  it("renders sizes, alertdialog role and no content while closed", () => {
    const markup = renderToStaticMarkup(
      <Modal
        onClose={() => undefined}
        open={false}
        role="alertdialog"
        size="sm"
        title="Titel"
      >
        Inhalt
      </Modal>,
    );
    expect(markup).toContain('class="modal modal-sm"');
    expect(markup).toContain('role="alertdialog"');
    expect(markup).not.toContain("Inhalt");
    expect(markup).not.toContain("style=");
  });
});
