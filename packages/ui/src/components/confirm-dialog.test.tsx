// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { installDialogPolyfill } from "../test-utils/dialog-polyfill";
import { ConfirmDialog } from "./confirm-dialog";

beforeAll(installDialogPolyfill);
afterEach(cleanup);

const base = {
  confirmLabel: "Kontakt sperren",
  description: "E-Mail-Akquise und Marketing werden gesperrt.",
  title: "Folgekontakt sperren?",
} as const;

describe("ConfirmDialog", () => {
  it("is a labelled, described alertdialog on the native dialog", () => {
    render(
      <ConfirmDialog
        {...base}
        onConfirm={vi.fn()}
        onOpenChange={vi.fn()}
        open
        tone="danger"
      />,
    );
    const dialog = screen.getByRole("alertdialog", {
      name: "Folgekontakt sperren?",
    });
    expect(dialog.tagName).toBe("DIALOG");
    expect(dialog.className).toContain("modal modal-sm");
    expect(dialog.getAttribute("aria-describedby")).toBe(
      screen.getByText(base.description).id,
    );
    expect(screen.getByText(base.description).className).toBe(
      "modal-description",
    );
  });

  it("puts ghost Abbrechen first and focuses it, then the tone verb", () => {
    render(
      <ConfirmDialog
        {...base}
        onConfirm={vi.fn()}
        onOpenChange={vi.fn()}
        open
        tone="danger"
      />,
    );
    const buttons = screen.getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual([
      "Abbrechen",
      "Kontakt sperren",
    ]);
    expect(buttons[0]?.className).toBe("btn btn-ghost btn-md");
    expect(buttons[1]?.className).toBe("btn btn-danger btn-md");
    expect(document.activeElement).toBe(buttons[0]);
  });

  it("confirms, cancels and closes on Esc through onOpenChange", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <ConfirmDialog
        {...base}
        onConfirm={onConfirm}
        onOpenChange={onOpenChange}
        open
      />,
    );
    await user.click(screen.getByRole("button", { name: "Kontakt sperren" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Abbrechen" }));
    expect(onOpenChange).toHaveBeenLastCalledWith(false);

    onOpenChange.mockClear();
    await user.keyboard("{Escape}");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("disables both actions and shows progress while pending", () => {
    render(
      <ConfirmDialog
        {...base}
        onConfirm={vi.fn()}
        onOpenChange={vi.fn()}
        open
        pending
      />,
    );
    expect(screen.getByRole("button", { name: "Abbrechen" })).toHaveProperty(
      "disabled",
      true,
    );
    const confirm = screen.getByRole("button", { name: "Wird gespeichert …" });
    expect(confirm).toHaveProperty("disabled", true);
    expect(confirm.getAttribute("aria-busy")).toBe("true");
  });
});
