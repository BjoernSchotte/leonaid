// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GripVertical } from "lucide-react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Button, IconButton } from "./button";

afterEach(cleanup);

describe("Button focusableWhenDisabled", () => {
  it("keeps focus when it disables itself after a press", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    function SavingButton() {
      const [saving, setSaving] = useState(false);
      return (
        <Button
          disabled={saving}
          focusableWhenDisabled
          onClick={() => {
            onSave();
            setSaving(true);
          }}
        >
          Nach oben
        </Button>
      );
    }
    render(<SavingButton />);
    const button = screen.getByRole("button", { name: "Nach oben" });
    button.focus();
    await user.keyboard("{Enter}");
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(button).toHaveProperty("disabled", false);
    expect(button.getAttribute("aria-disabled")).toBe("true");
    expect(document.activeElement).toBe(button);
    // Inert while disabled: neither keyboard nor pointer runs the action.
    await user.keyboard("{Enter}");
    await user.click(button);
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("does not submit its form while disabled", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn((event: SubmitEvent) => event.preventDefault());
    render(
      <form onSubmit={(event) => onSubmit(event.nativeEvent as SubmitEvent)}>
        <input aria-label="Tag" />
        <Button disabled focusableWhenDisabled type="submit">
          Planen
        </Button>
      </form>,
    );
    await user.click(screen.getByRole("button", { name: "Planen" }));
    await user.type(screen.getByLabelText("Tag"), "x{Enter}");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("uses the native disabled attribute without the opt-in", () => {
    render(<Button disabled>Speichern</Button>);
    const button = screen.getByRole("button", { name: "Speichern" });
    expect(button).toHaveProperty("disabled", true);
    expect(button.hasAttribute("aria-disabled")).toBe(false);
  });

  it("runs onClick normally while enabled", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <Button focusableWhenDisabled onClick={onClick}>
        Nach unten
      </Button>,
    );
    await user.click(screen.getByRole("button", { name: "Nach unten" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});

describe("IconButton focusableWhenDisabled", () => {
  it("keeps focus and ignores presses while disabled", async () => {
    const user = userEvent.setup();
    const onMove = vi.fn();
    function SavingIcon() {
      const [saving, setSaving] = useState(false);
      return (
        <IconButton
          disabled={saving}
          focusableWhenDisabled
          icon={GripVertical}
          label="Verschieben"
          onClick={() => {
            onMove();
            setSaving(true);
          }}
        />
      );
    }
    render(<SavingIcon />);
    const button = screen.getByRole("button", { name: "Verschieben" });
    button.focus();
    await user.keyboard(" ");
    expect(onMove).toHaveBeenCalledTimes(1);
    expect(button).toHaveProperty("disabled", false);
    expect(button.getAttribute("aria-disabled")).toBe("true");
    expect(button.hasAttribute("focusablewhendisabled")).toBe(false);
    expect(document.activeElement).toBe(button);
    await user.keyboard(" ");
    await user.click(button);
    expect(onMove).toHaveBeenCalledTimes(1);
  });

  it("uses the native disabled attribute without the opt-in", () => {
    render(<IconButton disabled icon={GripVertical} label="Verschieben" />);
    const button = screen.getByRole("button", { name: "Verschieben" });
    expect(button).toHaveProperty("disabled", true);
    expect(button.hasAttribute("aria-disabled")).toBe(false);
  });
});
