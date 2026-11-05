import { useEffect } from "react";

/**
 * WCAG 2.4.11 Focus Not Obscured, for browsers that ignore scroll-padding
 * when focus moves (WebKit, so Safari on the iPhone). The shells set
 * `scroll-padding-top/-bottom` on <html> for their sticky bars; Chromium and
 * Firefox keep a focused element clear of that padding by themselves. Here a
 * focused element that still sits in the padding (under a bar) is scrolled
 * into the clear by the missing distance. Where the browser already did it,
 * nothing happens.
 */
export function revealFocusedElement(
  element: Element,
  doc: Document = document,
): void {
  const view = doc.defaultView;
  const root = doc.documentElement;
  if (!view || !(element instanceof view.HTMLElement)) return;
  if (element.closest("dialog")) return; // modals scroll on their own
  // Bars, jump navs and other sticky or fixed parts do not move with the
  // page: scrolling cannot reveal them, it would only shift the page.
  for (
    let node: Element | null = element;
    node && node !== root;
    node = node.parentElement
  ) {
    const position = view.getComputedStyle(node).position;
    if (position === "sticky" || position === "fixed") return;
  }
  const style = view.getComputedStyle(root);
  const top = Number.parseFloat(style.scrollPaddingTop) || 0;
  const bottom = Number.parseFloat(style.scrollPaddingBottom) || 0;
  if (!top && !bottom) return;
  const box = element.getBoundingClientRect();
  if (box.height === 0) return;
  const clearBottom = view.innerHeight - bottom;
  let delta = 0;
  if (box.top < top) delta = box.top - top;
  else if (box.bottom > clearBottom && box.height <= clearBottom - top) {
    delta = box.bottom - clearBottom;
  }
  if (delta) view.scrollBy({ top: delta, behavior: "instant" });
}

/** Mounted once by each shell: reveals elements as they receive focus. */
export function useFocusNotObscured(): void {
  useEffect(() => {
    let frame = 0;
    const onFocusIn = (event: FocusEvent) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      cancelAnimationFrame(frame);
      // Wait until the browser's own (possibly smooth) focus scrolling has
      // stopped, then fill only what is still missing.
      let last = Number.NaN;
      let still = 0;
      let frames = 0;
      const step = () => {
        frames += 1;
        still = window.scrollY === last ? still + 1 : 0;
        last = window.scrollY;
        if (still >= 2 || frames > 60) {
          if (document.activeElement === target) revealFocusedElement(target);
          return;
        }
        frame = requestAnimationFrame(step);
      };
      frame = requestAnimationFrame(step);
    };
    document.addEventListener("focusin", onFocusIn);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("focusin", onFocusIn);
    };
  }, []);
}
