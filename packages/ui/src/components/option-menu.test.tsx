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

// jsdom lacks ResizeObserver; this one lets tests trigger the callbacks.
const resizeCallbacks = new Set<() => void>();
class TestResizeObserver {
  constructor(private readonly callback: () => void) {}
  observe() {
    resizeCallbacks.add(this.callback);
  }
  unobserve() {
    resizeCallbacks.delete(this.callback);
  }
  disconnect() {
    resizeCallbacks.delete(this.callback);
  }
}

beforeAll(() => {
  globalThis.ResizeObserver =
    TestResizeObserver as unknown as typeof ResizeObserver;
  // cmdk scrolls the active item into view.
  Element.prototype.scrollIntoView ??= () => {};
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  resizeCallbacks.clear();
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
  inDialog,
}: {
  multiple?: boolean;
  onSelect?: (value: Status) => void;
  inDialog?: boolean;
}) {
  const anchor = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const Wrapper = inDialog ? "dialog" : "div";
  return (
    <Wrapper open={inDialog || undefined}>
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
    </Wrapper>
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

  it("ignores number keys with Ctrl, Meta or Alt held", () => {
    const onSelect = vi.fn();
    render(<Harness onSelect={onSelect} />);
    const input = openMenu();
    fireEvent.keyDown(input, { key: "1", ctrlKey: true });
    fireEvent.keyDown(input, { key: "1", metaKey: true });
    fireEvent.keyDown(input, { key: "1", altKey: true });
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeTruthy();
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
    expect(
      screen.getByRole("listbox").getAttribute("aria-multiselectable"),
    ).toBe("true");
  });

  it("is not multiselectable for a single value", () => {
    render(<Harness />);
    openMenu();
    expect(
      screen.getByRole("listbox").hasAttribute("aria-multiselectable"),
    ).toBe(false);
  });

  it("portals into the dialog that contains the trigger", () => {
    render(<Harness inDialog />);
    openMenu();
    const layer = screen.getByRole("dialog", { name: "Status ändern" });
    expect(layer.parentElement?.tagName).toBe("DIALOG");
  });

  it("portals to the body outside a dialog", () => {
    render(<Harness />);
    openMenu();
    expect(screen.getByRole("dialog").parentElement).toBe(document.body);
  });

  it("stays attached above the trigger when the list height changes", () => {
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Status" });
    vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue(
      new DOMRect(100, 700, 80, 30),
    );
    let height = 300;
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockImplementation(
      () => height,
    );
    vi.spyOn(window, "innerHeight", "get").mockReturnValue(800);
    openMenu();
    const layer = screen.getByRole("dialog");
    const y = () => layer.style.getPropertyValue("--pop-y");
    expect(y()).toBe(`${700 - 300 - 6}px`);
    height = 80;
    act(() => {
      for (const callback of resizeCallbacks) callback();
    });
    expect(y()).toBe(`${700 - 80 - 6}px`);
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
