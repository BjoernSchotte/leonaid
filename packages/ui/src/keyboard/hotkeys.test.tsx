// @vitest-environment jsdom
import { act, cleanup, render, screen, within } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  HOTKEY_PASSTHROUGH_ATTRIBUTE,
  HotkeyRegistry,
  normaliseEvent,
  SEQUENCE_TIMEOUT_MS,
  type HotkeyBinding,
} from "./hotkeys";
import { PrefixHint } from "./prefix-hint";
import { GO_TO_GROUP, ShortcutHelp } from "./shortcut-help";
import { HotkeyProvider, useHotkeys } from "./use-hotkeys";

function press(
  key: string,
  init: KeyboardEventInit = {},
  target: EventTarget = document.activeElement ?? document.body,
) {
  const event = new KeyboardEvent("keydown", {
    key,
    bubbles: true,
    cancelable: true,
    ...init,
  });
  act(() => {
    target.dispatchEvent(event);
  });
  return event;
}

function Bindings({ bindings }: { bindings: readonly HotkeyBinding[] }) {
  useHotkeys(bindings);
  return null;
}

function setup(bindings: readonly HotkeyBinding[], extra?: ReactNode) {
  return render(
    <HotkeyProvider>
      <Bindings bindings={bindings} />
      {extra}
    </HotkeyProvider>,
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(navigator, "platform", "get").mockReturnValue("Win32");
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("sequences", () => {
  it("runs g then t within 1200 ms", () => {
    const run = vi.fn();
    setup([{ keys: "g t", label: "Aufgaben", group: GO_TO_GROUP, run }]);
    press("g");
    act(() => vi.advanceTimersByTime(1100));
    press("t");
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("does not run g then t after 1300 ms", () => {
    const run = vi.fn();
    setup([{ keys: "g t", label: "Aufgaben", group: GO_TO_GROUP, run }]);
    press("g");
    act(() => vi.advanceTimersByTime(1300));
    press("t");
    expect(run).not.toHaveBeenCalled();
    expect(SEQUENCE_TIMEOUT_MS).toBe(1200);
  });

  it("does not let the second key fall through to a single-key binding", () => {
    const sequence = vi.fn();
    const single = vi.fn();
    setup([
      { keys: "g t", label: "Aufgaben", group: GO_TO_GROUP, run: sequence },
      { keys: "x", label: "Abhaken", group: "Liste", run: single },
    ]);
    press("g");
    press("x");
    expect(single).not.toHaveBeenCalled();
    press("x");
    expect(single).toHaveBeenCalledTimes(1);
  });

  it("does not start a sequence while typing", () => {
    const run = vi.fn();
    setup(
      [{ keys: "g t", label: "Aufgaben", group: GO_TO_GROUP, run }],
      <input aria-label="Suche" />,
    );
    const input = screen.getByLabelText("Suche");
    input.focus();
    press("g");
    press("t");
    expect(run).not.toHaveBeenCalled();
  });

  it("shows the prefix hint until the timeout", () => {
    setup(
      [
        { keys: "g d", label: "Übersicht", group: GO_TO_GROUP, run: vi.fn() },
        {
          keys: "g b",
          label: "Bestellungen",
          group: GO_TO_GROUP,
          run: vi.fn(),
        },
      ],
      <PrefixHint />,
    );
    expect(screen.queryByRole("status")).toBeNull();
    press("g");
    const hint = screen.getByRole("status");
    expect(hint.textContent).toContain("gedrückt – jetzt Ziel wählen");
    expect(hint.textContent).toContain("Bestellungen");
    act(() => vi.advanceTimersByTime(SEQUENCE_TIMEOUT_MS));
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("typing guard", () => {
  const cases: [string, ReactNode][] = [
    ["textarea", <textarea aria-label="Feld" key="t" />],
    ["input", <input aria-label="Feld" key="i" />],
    [
      "select",
      <select aria-label="Feld" key="s">
        <option>a</option>
      </select>,
    ],
    [
      "contenteditable",
      <div aria-label="Feld" contentEditable key="c" tabIndex={0} />,
    ],
  ];

  it.each(cases)("ignores j while a %s has focus", (_name, field) => {
    const run = vi.fn();
    setup([{ keys: "j", label: "Nächste Zeile", group: "Liste", run }], field);
    screen.getByLabelText("Feld").focus();
    const event = press("j");
    expect(run).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false);
  });

  it("ignores j inside a nested contenteditable node", () => {
    const run = vi.fn();
    setup(
      [{ keys: "j", label: "Nächste Zeile", group: "Liste", run }],
      <div contentEditable>
        <p>
          <strong data-testid="inner">Text</strong>
        </p>
      </div>,
    );
    press("j", {}, screen.getByTestId("inner"));
    expect(run).not.toHaveBeenCalled();
  });

  it("runs j on a checkbox", () => {
    const run = vi.fn();
    setup(
      [{ keys: "j", label: "Nächste Zeile", group: "Liste", run }],
      <input aria-label="Feld" type="checkbox" />,
    );
    screen.getByLabelText("Feld").focus();
    press("j");
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("still runs mod+k while typing", () => {
    const run = vi.fn();
    setup(
      [{ keys: "mod+k", label: "Befehle", group: "Allgemein", run }],
      <textarea aria-label="Feld" />,
    );
    screen.getByLabelText("Feld").focus();
    const event = press("k", { ctrlKey: true });
    expect(run).toHaveBeenCalledTimes(1);
    expect(event.defaultPrevented).toBe(true);
  });

  it("ignores IME composition", () => {
    const run = vi.fn();
    setup([{ keys: "j", label: "Nächste Zeile", group: "Liste", run }]);
    press("j", { isComposing: true });
    press("j", { keyCode: 229 });
    expect(run).not.toHaveBeenCalled();
  });

  it("skips events another handler already handled", () => {
    const run = vi.fn();
    setup([{ keys: "j", label: "Nächste Zeile", group: "Liste", run }]);
    const event = new KeyboardEvent("keydown", {
      key: "j",
      bubbles: true,
      cancelable: true,
    });
    event.preventDefault();
    act(() => {
      document.body.dispatchEvent(event);
    });
    expect(run).not.toHaveBeenCalled();
  });

  it("keeps Enter native on buttons", () => {
    const run = vi.fn();
    setup(
      [{ keys: "enter", label: "Öffnen", group: "Liste", run }],
      <button type="button">Knopf</button>,
    );
    screen.getByRole("button").focus();
    press("Enter");
    expect(run).not.toHaveBeenCalled();
  });
});

describe("dialog guard", () => {
  it("ignores single keys and sequences while another dialog is open", () => {
    const single = vi.fn();
    const sequence = vi.fn();
    const palette = vi.fn();
    setup(
      [
        { keys: "j", label: "Nächste Zeile", group: "Liste", run: single },
        { keys: "g t", label: "Aufgaben", group: GO_TO_GROUP, run: sequence },
        {
          keys: "mod+k",
          label: "Befehle",
          group: "Allgemein",
          inDialog: true,
          run: palette,
        },
      ],
      <dialog open>
        <button type="button">Im Dialog</button>
      </dialog>,
    );
    screen.getByRole("button").focus();
    press("j");
    press("g");
    press("t");
    expect(single).not.toHaveBeenCalled();
    expect(sequence).not.toHaveBeenCalled();
    press("k", { ctrlKey: true });
    expect(palette).toHaveBeenCalledTimes(1);
  });

  it("does not mute bindings for the palette dialog", () => {
    const run = vi.fn();
    setup(
      [{ keys: "g t", label: "Aufgaben", group: GO_TO_GROUP, run }],
      <dialog open {...{ [HOTKEY_PASSTHROUGH_ATTRIBUTE]: "" }}>
        <button type="button">Befehl</button>
      </dialog>,
    );
    screen.getByRole("button").focus();
    press("g");
    press("t");
    expect(run).toHaveBeenCalledTimes(1);
  });
});

describe("registry", () => {
  it("removes bindings when their component unmounts", () => {
    const run = vi.fn();
    function Toggle() {
      const [shown, setShown] = useState(true);
      return (
        <>
          {shown ? (
            <Bindings
              bindings={[{ keys: "x", label: "Abhaken", group: "Liste", run }]}
            />
          ) : null}
          <button onClick={() => setShown(false)} type="button">
            weg
          </button>
        </>
      );
    }
    render(
      <HotkeyProvider>
        <Toggle />
      </HotkeyProvider>,
    );
    press("x", {}, document.body);
    expect(run).toHaveBeenCalledTimes(1);
    act(() => screen.getByRole("button").click());
    press("x", {}, document.body);
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("lets later registrations win and falls back after unmount", () => {
    const shell = vi.fn();
    const page = vi.fn();
    const registry = new HotkeyRegistry();
    const first = registry.register([
      { keys: "c", label: "Neu", group: "Allgemein", run: shell },
    ]);
    const second = registry.register([
      { keys: "c", label: "Neue Aufgabe", group: "Liste", run: page },
    ]);
    const fire = () =>
      registry.handleKeyDown(new KeyboardEvent("keydown", { key: "c" }));
    fire();
    expect(page).toHaveBeenCalledTimes(1);
    expect(registry.getVisible().map((entry) => entry.label)).toEqual([
      "Neue Aufgabe",
    ]);
    second.dispose();
    fire();
    expect(shell).toHaveBeenCalledTimes(1);
    first.dispose();
    expect(registry.getAll()).toEqual([]);
  });

  it("respects when()", () => {
    const run = vi.fn();
    let enabled = false;
    setup([
      {
        keys: "x",
        label: "Abhaken",
        group: "Liste",
        when: () => enabled,
        run,
      },
    ]);
    press("x", {}, document.body);
    expect(run).not.toHaveBeenCalled();
    enabled = true;
    press("x", {}, document.body);
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("calls the latest run closure without re-registering", () => {
    const calls: number[] = [];
    function Counter() {
      const [count, setCount] = useState(0);
      useHotkeys([
        {
          keys: "x",
          label: "Zählen",
          group: "Liste",
          run: () => {
            calls.push(count);
            setCount(count + 1);
          },
        },
      ]);
      return null;
    }
    render(
      <HotkeyProvider>
        <Counter />
      </HotkeyProvider>,
    );
    press("x", {}, document.body);
    press("x", {}, document.body);
    expect(calls).toEqual([0, 1]);
  });
});

describe("normaliseEvent", () => {
  const ev = (key: string, init: KeyboardEventInit = {}) =>
    new KeyboardEvent("keydown", { key, ...init });

  it("maps platform modifiers", () => {
    expect(normaliseEvent(ev("k", { ctrlKey: true }), false)).toBe("mod+k");
    expect(normaliseEvent(ev("k", { metaKey: true }), true)).toBe("mod+k");
    expect(normaliseEvent(ev("k", { metaKey: true }), false)).toBe("meta+k");
    expect(normaliseEvent(ev("k", { ctrlKey: true }), true)).toBe("ctrl+k");
  });

  it("keeps shifted symbols and marks shifted letters", () => {
    expect(normaliseEvent(ev("?", { shiftKey: true }), false)).toBe("?");
    expect(normaliseEvent(ev("T", { shiftKey: true }), false)).toBe("shift+t");
    expect(normaliseEvent(ev(" "), false)).toBe("space");
    expect(normaliseEvent(ev("Shift", { shiftKey: true }), false)).toBeNull();
  });
});

describe("ShortcutHelp", () => {
  it("opens on ? and lists every registered binding with its group", () => {
    setup(
      [
        { keys: "j", label: "Nächste Zeile", group: "Liste", run: vi.fn() },
        { keys: "x", label: "Zeile abhaken", group: "Liste", run: vi.fn() },
        { keys: "mod+k", label: "Befehle", group: "Allgemein", run: vi.fn() },
        {
          keys: "arrowdown",
          label: "Nächste Zeile",
          group: "Liste",
          hidden: true,
          run: vi.fn(),
        },
        {
          keys: "g t",
          label: "Aufgaben",
          group: GO_TO_GROUP,
          zone: "tasks",
          run: vi.fn(),
        },
      ],
      <ShortcutHelp />,
    );
    expect(screen.queryByRole("heading", { name: "Tastenkürzel" })).toBeNull();
    press("?", { shiftKey: true }, document.body);
    const dialog = screen.getByRole("dialog", { name: "Tastenkürzel" });

    const section = (name: string) =>
      within(dialog).getByRole("heading", { name, level: 3 }).parentElement!;
    const labels = (name: string) =>
      [...section(name).querySelectorAll("li > span:first-child")].map(
        (node) => node.textContent,
      );

    expect(
      within(dialog)
        .getAllByRole("heading", { level: 3 })
        .map((node) => node.textContent),
    ).toEqual(["Liste", "Allgemein", GO_TO_GROUP]);
    // The hidden "arrowdown" alias is not listed.
    expect(labels("Liste")).toEqual(["Nächste Zeile", "Zeile abhaken"]);
    expect(labels("Allgemein")).toEqual(["Befehle", "Tastenkürzel anzeigen"]);
    expect(labels(GO_TO_GROUP)).toEqual(["Aufgaben"]);
    expect(section(GO_TO_GROUP).querySelector("li")?.dataset.zone).toBe(
      "tasks",
    );
    expect(section("Allgemein").textContent).toContain("Strg plus K");

    press("?", { shiftKey: true });
    expect(screen.queryByRole("heading", { name: "Tastenkürzel" })).toBeNull();
  });

  it("lists bindings only while their component is mounted", () => {
    function Page() {
      useHotkeys([
        { keys: "c", label: "Neue Aufgabe", group: "Aufgaben", run: vi.fn() },
      ]);
      return null;
    }
    function Screen() {
      const [page, setPage] = useState(true);
      return (
        <>
          {page ? <Page /> : null}
          <button onClick={() => setPage(false)} type="button">
            Seite wechseln
          </button>
          <ShortcutHelp />
        </>
      );
    }
    render(
      <HotkeyProvider>
        <Screen />
      </HotkeyProvider>,
    );
    press("?", {}, document.body);
    expect(screen.getByText("Neue Aufgabe")).toBeTruthy();
    press("?");
    act(() => screen.getByRole("button", { name: "Seite wechseln" }).click());
    press("?", {}, document.body);
    expect(screen.queryByText("Neue Aufgabe")).toBeNull();
  });
});
