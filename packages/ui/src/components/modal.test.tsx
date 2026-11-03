// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { installDialogPolyfill } from "../test-utils/dialog-polyfill";
import { ConfirmDialog } from "./confirm-dialog";
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

    const dialog = screen.getByRole("dialog");
    fireEvent.pointerDown(dialog);
    fireEvent.click(dialog);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not close when a drag starts inside and ends on the backdrop", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    await user.click(screen.getByRole("button", { name: "Öffnen" }));
    fireEvent.pointerDown(screen.getByRole("textbox", { name: "Grund" }));
    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("reports a close the browser forced (second Esc in Chromium)", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    const opener = screen.getByRole("button", { name: "Öffnen" });
    await user.click(opener);

    // The browser may close without a cancelable `cancel` event.
    act(() => (document.querySelector("dialog") as HTMLDialogElement).close());

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(opener);
  });

  it("re-opens after a forced close when the consumer keeps it open", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    function Stubborn() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button onClick={() => setOpen(true)} type="button">
            Öffnen
          </button>
          <Modal onClose={onClose} open={open} title="Wird gespeichert">
            <input aria-label="Grund" />
          </Modal>
        </>
      );
    }
    render(<Stubborn />);
    await user.click(screen.getByRole("button", { name: "Öffnen" }));
    const dialog = document.querySelector("dialog") as HTMLDialogElement;
    act(() => dialog.close());
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(dialog.open).toBe(true);
    expect(document.documentElement.classList.contains("modal-open")).toBe(
      true,
    );
  });

  it("ignores cancel and close events of nested elements", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    await user.click(screen.getByRole("button", { name: "Öffnen" }));
    const input = screen.getByRole("textbox", { name: "Grund" });
    // A dismissed file picker fires `cancel` on its input.
    fireEvent(input, new Event("cancel", { bubbles: true, cancelable: true }));
    fireEvent(input, new Event("close", { bubbles: true }));
    expect(onClose).not.toHaveBeenCalled();
    expect(document.querySelector("dialog")?.open).toBe(true);
  });

  it("closes only the nested ConfirmDialog on Esc and Abbrechen", async () => {
    const user = userEvent.setup();
    const outerClose = vi.fn();
    const innerChange = vi.fn();
    function Nested() {
      const [confirm, setConfirm] = useState(false);
      return (
        <Modal onClose={outerClose} open title="Bearbeiten">
          <button onClick={() => setConfirm(true)} type="button">
            Löschen
          </button>
          <ConfirmDialog
            confirmLabel="Löschen"
            description="Der Eintrag wird entfernt."
            onConfirm={() => undefined}
            onOpenChange={(open) => {
              innerChange(open);
              setConfirm(open);
            }}
            open={confirm}
            title="Eintrag löschen?"
          />
        </Modal>
      );
    }
    render(<Nested />);
    const opener = screen.getByRole("button", { name: "Löschen" });
    await user.click(opener);
    expect(screen.getByRole("alertdialog")).toBeTruthy();

    await user.keyboard("{Escape}");
    expect(innerChange).toHaveBeenCalledWith(false);
    expect(outerClose).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(opener);

    await user.click(opener);
    await user.click(screen.getByRole("button", { name: "Abbrechen" }));
    expect(outerClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Bearbeiten" })).toHaveProperty(
      "open",
      true,
    );
  });

  it("opens a child modal on top when parent and child open together", async () => {
    const order: string[] = [];
    const original = HTMLDialogElement.prototype.showModal;
    const spy = vi
      .spyOn(HTMLDialogElement.prototype, "showModal")
      .mockImplementation(function (this: HTMLDialogElement) {
        order.push(this.getAttribute("aria-labelledby") ?? "");
        original.call(this);
      });
    await act(async () => {
      render(
        <Modal onClose={() => undefined} open title="Eltern">
          <Modal onClose={() => undefined} open title="Kind">
            Inhalt
          </Modal>
        </Modal>,
      );
    });
    spy.mockRestore();
    const parent = screen.getByRole("dialog", { name: "Eltern" });
    const child = screen.getByRole("dialog", { name: "Kind" });
    expect(order).toEqual([
      parent.getAttribute("aria-labelledby"),
      child.getAttribute("aria-labelledby"),
    ]);
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
