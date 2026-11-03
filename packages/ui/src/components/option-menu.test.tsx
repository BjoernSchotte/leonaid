// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { OptionMenu, type OptionMenuOption } from "./option-menu";
import { Popover } from "./popover";

beforeAll(() => {
  // jsdom lacks both; cmdk uses them for list height and active-item scroll.
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  Element.prototype.scrollIntoView ??= () => {};
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

type Status = "open" | "doing" | "done";

const options: OptionMenuOption<Status>[] = [
  { value: "open", label: "Offen" },
  { value: "doing", label: "In Arbeit", hint: "aktiv" },
  { value: "done", label: "Erledigt" },
];

function Harness({
  multiple,
  onSelect = () => {},
}: {
  multiple?: boolean;
  onSelect?: (value: Status) => void;
}) {
  const anchor = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)} ref={anchor} type="button">
        Status
      </button>
      <Popover
        anchor={anchor}
        label="Status ändern"
        onClose={() => setOpen(false)}
        open={open}
      >
        <OptionMenu
          multiple={multiple}
          onSelect={(value) => {
            onSelect(value);
            if (!multiple) setOpen(false);
          }}
          options={options}
          placeholder="Status ändern …"
          value={multiple ? ["open", "done"] : "doing"}
        />
      </Popover>
    </>
  );
}

function openMenu() {
  fireEvent.click(screen.getByRole("button", { name: "Status" }));
  return screen.getByRole("combobox", { name: "Status ändern …" });
}

const visibleLabels = () =>
  screen.getAllByRole("option").map((option) => option.textContent);

describe("Popover with OptionMenu", () => {
  it("renders nothing while closed", () => {
    render(<Harness />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens as a labelled dialog and focuses the search input", async () => {
    render(<Harness />);
    const input = openMenu();
    expect(screen.getByRole("dialog", { name: "Status ändern" })).toBeTruthy();
    await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
    expect(document.activeElement).toBe(input);
  });

  it("filters the options while typing", () => {
    render(<Harness />);
    const input = openMenu();
    expect(visibleLabels()).toHaveLength(3);
    fireEvent.change(input, { target: { value: "erl" } });
    expect(visibleLabels()).toEqual([expect.stringContaining("Erledigt")]);
    fireEvent.change(input, { target: { value: "zzz" } });
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    expect(screen.getByText("Nichts gefunden")).toBeTruthy();
  });

  it("selects the active option with Enter", () => {
    const onSelect = vi.fn();
    render(<Harness onSelect={onSelect} />);
    const input = openMenu();
    fireEvent.change(input, { target: { value: "arbeit" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("doing");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("moves the active option with the arrow keys", () => {
    const onSelect = vi.fn();
    render(<Harness onSelect={onSelect} />);
    const input = openMenu();
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("doing");
  });

  it("picks an option with its number key while the search is empty", () => {
    const onSelect = vi.fn();
    render(<Harness onSelect={onSelect} />);
    const input = openMenu();
    fireEvent.keyDown(input, { key: "3" });
    expect(onSelect).toHaveBeenCalledWith("done");
  });

  it("does not treat number keys as picks while searching", () => {
    const onSelect = vi.fn();
    render(<Harness onSelect={onSelect} />);
    const input = openMenu();
    fireEvent.change(input, { target: { value: "e" } });
    fireEvent.keyDown(input, { key: "1" });
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("marks the current value as checked", () => {
    render(<Harness />);
    openMenu();
    const checked = screen
      .getAllByRole("option")
      .filter((option) => option.getAttribute("aria-checked") === "true");
    expect(checked.map((option) => option.textContent)).toEqual([
      expect.stringContaining("In Arbeit"),
    ]);
    expect(screen.getByText("aktiv").className).toBe("menu-hint");
  });

  it("marks every selected value and hides number keys when multiple", () => {
    render(<Harness multiple />);
    openMenu();
    const checked = screen
      .getAllByRole("option")
      .filter((option) => option.getAttribute("aria-checked") === "true");
    expect(checked).toHaveLength(2);
    expect(document.querySelector(".menu-item .kbd-group")).toBeNull();
  });

  it("closes with Escape and returns focus to the trigger", () => {
    render(<Harness />);
    const input = openMenu();
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Status" }),
    );
  });

  it("closes on a pointer press outside", () => {
    render(<Harness />);
    openMenu();
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("positions through CSSOM and adds no <style> element (strict CSP)", () => {
    const setProperty = vi.spyOn(CSSStyleDeclaration.prototype, "setProperty");
    const stylesBefore = document.head.querySelectorAll("style").length;
    render(<Harness />);
    openMenu();
    const layer = screen.getByRole("dialog");
    expect(layer.classList.contains("is-placed")).toBe(true);
    expect(setProperty).toHaveBeenCalledWith("--pop-x", expect.any(String));
    expect(setProperty).toHaveBeenCalledWith("--pop-y", expect.any(String));
    expect(document.head.querySelectorAll("style")).toHaveLength(stylesBefore);
    expect(document.querySelectorAll("style")).toHaveLength(stylesBefore);
  });
});
