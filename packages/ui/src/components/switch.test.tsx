// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { Switch } from "./switch";

afterEach(cleanup);

function Harness({ disabled = false }: { readonly disabled?: boolean }) {
  const [checked, setChecked] = useState(false);
  return (
    <Switch
      checked={checked}
      disabled={disabled}
      label="Pflichtfrage"
      onChange={(event) => setChecked(event.target.checked)}
    />
  );
}

describe("Switch", () => {
  it("is a native checkbox with the switch role over the prototype track", () => {
    render(<Harness />);
    const control = screen.getByRole("switch", { name: "Pflichtfrage" });
    expect(control.getAttribute("type")).toBe("checkbox");
    expect(control.parentElement?.className).toBe("switch");
    const track = control.nextElementSibling;
    expect(track?.className).toBe("switch-track");
    expect(track?.getAttribute("aria-hidden")).toBe("true");
    expect(control.closest("label")?.className).toBe("switch-row");
  });

  it("toggles by click on the label and by Space", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const control = screen.getByRole("switch", { name: "Pflichtfrage" });
    await user.click(screen.getByText("Pflichtfrage"));
    expect(control).toHaveProperty("checked", true);
    await user.keyboard(" ");
    expect(control).toHaveProperty("checked", false);
  });

  it("does not toggle while disabled", async () => {
    const user = userEvent.setup();
    render(<Harness disabled />);
    const control = screen.getByRole("switch", { name: "Pflichtfrage" });
    await user.click(control);
    expect(control).toHaveProperty("checked", false);
  });

  it("renders without a label wrapper when labelled elsewhere", () => {
    render(<Switch aria-label="Modul aktiv" defaultChecked />);
    const control = screen.getByRole("switch", { name: "Modul aktiv" });
    expect(control.closest("label")).toBeNull();
    expect(control).toHaveProperty("checked", true);
  });
});
