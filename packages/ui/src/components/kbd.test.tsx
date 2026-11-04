// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Kbd, keyLabels, keySpeech } from "./kbd";

function onPlatform(platform: string) {
  vi.spyOn(navigator, "platform", "get").mockReturnValue(platform);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const caps = (container: HTMLElement) =>
  [...container.querySelectorAll("kbd")].map((cap) => cap.textContent);

describe("Kbd", () => {
  it("renders Strg when the platform is not a Mac", () => {
    onPlatform("Win32");
    const { container } = render(<Kbd keys="mod+k" />);
    expect(caps(container)).toEqual(["Strg", "K"]);
  });

  it("renders ⌘ on a Mac", () => {
    onPlatform("MacIntel");
    const { container } = render(<Kbd keys={["mod+k"]} />);
    expect(caps(container)).toEqual(["⌘", "K"]);
  });

  it("joins sequence steps with dann", () => {
    onPlatform("Linux x86_64");
    const { container } = render(<Kbd keys={["g", "b"]} />);
    expect(caps(container)).toEqual(["G", "B"]);
    expect(container.querySelector(".kbd-then")?.textContent).toBe("dann");
    expect(
      container.querySelector(".kbd-group")?.getAttribute("aria-hidden"),
    ).toBe("true");
  });

  it("labels special keys in German", () => {
    onPlatform("Win32");
    expect(keyLabels("shift+alt+escape enter space arrowup")).toEqual([
      ["⇧", "Alt", "Esc"],
      ["↵"],
      ["Leertaste"],
      ["↑"],
    ]);
  });

  it("announces the binding as text for assistive tech", () => {
    onPlatform("Win32");
    const { container } = render(<Kbd keys="mod+k" />);
    const text = container.querySelector(".kbd-text");
    expect(text?.textContent).toBe("Strg plus K");
    expect(text?.closest("[aria-hidden]")).toBeNull();
  });

  it("announces sequences and symbols in German", () => {
    onPlatform("MacIntel");
    expect(keySpeech("g b")).toBe("G dann B");
    expect(keySpeech("mod+shift+enter")).toBe(
      "Befehl plus Umschalt plus Eingabe",
    );
    expect(keySpeech("? / escape space arrowdown")).toBe(
      "Fragezeichen dann Schrägstrich dann Escape dann Leertaste dann Pfeil nach unten",
    );
  });

  it("stays silent when the surrounding control already names the action", () => {
    const { container } = render(<Kbd announce={false} keys="c" />);
    expect(container.querySelector(".kbd-text")).toBeNull();
  });

  it("marks subtle keycaps", () => {
    const markup = renderToStaticMarkup(<Kbd keys="c" subtle />);
    expect(markup).toContain('class="kbd-group is-subtle"');
  });
});
