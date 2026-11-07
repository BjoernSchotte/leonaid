// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Button } from "./button";

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
