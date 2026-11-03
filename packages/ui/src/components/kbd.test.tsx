// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Kbd, keyLabels } from "./kbd";

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
    expect(container.firstElementChild?.getAttribute("aria-hidden")).toBe(
      "true",
    );
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

  it("marks subtle keycaps", () => {
    const markup = renderToStaticMarkup(<Kbd keys="c" subtle />);
    expect(markup).toContain('class="kbd-group is-subtle"');
  });
});
