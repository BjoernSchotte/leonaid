// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { revealFocusedElement } from "./focus-clear";

function place(element: HTMLElement, top: number, height = 40) {
  element.getBoundingClientRect = () =>
    ({
      top,
      bottom: top + height,
      height,
      left: 0,
      right: 100,
      width: 100,
    }) as DOMRect;
}

describe("revealFocusedElement", () => {
  let scrollBy: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    document.documentElement.style.setProperty("scroll-padding-top", "60px");
    document.documentElement.style.setProperty("scroll-padding-bottom", "70px");
    Object.defineProperty(window, "innerHeight", {
      value: 800,
      configurable: true,
    });
    scrollBy = vi.fn();
    window.scrollBy = scrollBy as unknown as typeof window.scrollBy;
  });
  afterEach(() => {
    document.documentElement.removeAttribute("style");
    document.body.innerHTML = "";
  });

  it("scrolls an element under the top bar into the clear", () => {
    const button = document.body.appendChild(document.createElement("button"));
    place(button, 20);
    revealFocusedElement(button);
    expect(scrollBy).toHaveBeenCalledWith({ top: -40, behavior: "instant" });
  });

  it("scrolls an element under the bottom bar up", () => {
    const button = document.body.appendChild(document.createElement("button"));
    place(button, 750);
    revealFocusedElement(button);
    expect(scrollBy).toHaveBeenCalledWith({ top: 60, behavior: "instant" });
  });

  it("leaves an element in the clear alone", () => {
    const button = document.body.appendChild(document.createElement("button"));
    place(button, 300);
    revealFocusedElement(button);
    expect(scrollBy).not.toHaveBeenCalled();
  });

  it("leaves elements in dialogs and pages without scroll-padding alone", () => {
    const dialog = document.body.appendChild(document.createElement("dialog"));
    const inDialog = dialog.appendChild(document.createElement("button"));
    place(inDialog, 10);
    revealFocusedElement(inDialog);
    document.documentElement.removeAttribute("style");
    const plain = document.body.appendChild(document.createElement("button"));
    place(plain, 10);
    revealFocusedElement(plain);
    expect(scrollBy).not.toHaveBeenCalled();
  });

  it("leaves elements inside sticky or fixed parts alone", () => {
    const nav = document.body.appendChild(document.createElement("nav"));
    nav.style.position = "sticky";
    const link = nav.appendChild(document.createElement("a"));
    link.href = "#x";
    place(link, 20);
    revealFocusedElement(link);
    expect(scrollBy).not.toHaveBeenCalled();
  });
});
