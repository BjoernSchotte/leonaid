// WCAG 2.4.11 Focus Not Obscured: a keyboard step to an element that sits
// under a sticky or fixed bar must bring it fully into the clear.
import { expect } from "./csp-guard.mjs";

/**
 * Puts a real tabbable element of `scope` (below the fold) right under
 * `cover` (the top bar for edge "top", a bottom bar for edge "bottom"),
 * focuses the tabbable before it, presses Tab and checks that the newly
 * focused element is not covered: its box is clear of the bar and
 * elementFromPoint at its centre hits the element itself.
 */
export async function expectTabNotObscured(page, { scope, cover, edge }) {
  const coverBox = await page.locator(cover).first().boundingBox();
  expect(coverBox, `${cover} is visible`).not.toBeNull();
  const prepared = await page.evaluate(
    ({ scope, edge, coverTop, coverBottom }) => {
      const selector =
        'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
      const tabbables = [...document.querySelectorAll(selector)].filter(
        (element) =>
          element.getClientRects().length > 0 &&
          getComputedStyle(element).visibility !== "hidden" &&
          !element.closest(
            "[inert], [hidden], dialog:not([open]), details:not([open]) > :not(summary)",
          ),
      );
      const scrollHeight = document.documentElement.scrollHeight;
      for (let index = 1; index < tabbables.length; index += 1) {
        const target = tabbables[index];
        const before = tabbables[index - 1];
        if (!target.closest(scope) || !before.closest(scope)) continue;
        const box = target.getBoundingClientRect();
        const top = box.top + window.scrollY;
        if (box.height === 0 || box.height > 120) continue;
        if (top < window.innerHeight || top > scrollHeight - window.innerHeight)
          continue;
        document
          .querySelectorAll("[data-obscure-target], [data-obscure-before]")
          .forEach((element) => {
            delete element.dataset.obscureTarget;
            delete element.dataset.obscureBefore;
          });
        target.dataset.obscureTarget = "";
        before.dataset.obscureBefore = "";
        before.focus({ preventScroll: true });
        // Park the target half under the bar: still "in the viewport", so
        // without scroll-padding a browser does not scroll on focus.
        const now = target.getBoundingClientRect();
        if (edge === "top") {
          window.scrollBy(0, now.top - (coverBottom - now.height / 2));
        } else {
          window.scrollBy(0, now.bottom - (coverTop + now.height / 2));
        }
        return true;
      }
      return false;
    },
    {
      scope,
      edge,
      coverTop: coverBox.y,
      coverBottom: coverBox.y + coverBox.height,
    },
  );
  expect(prepared, `a tabbable pair below the fold in ${scope}`).toBe(true);
  const target = page.locator("[data-obscure-target]");
  const startBox = await target.boundingBox();
  if (edge === "top") {
    expect(startBox.y, "the target starts under the bar").toBeLessThan(
      coverBox.y + coverBox.height,
    );
  } else {
    expect(startBox.y + startBox.height).toBeGreaterThan(coverBox.y);
  }

  await page.keyboard.press("Tab");
  await expect(target).toBeFocused();
  const result = await target.evaluate(
    (element, { coverSelector }) => {
      const box = element.getBoundingClientRect();
      const bar = document.querySelector(coverSelector).getBoundingClientRect();
      const hit = document.elementFromPoint(
        box.left + Math.min(box.width / 2, 20),
        box.top + box.height / 2,
      );
      return {
        top: box.top,
        bottom: box.bottom,
        barTop: bar.top,
        barBottom: bar.bottom,
        hitsTarget: Boolean(hit && (hit === element || element.contains(hit))),
      };
    },
    { coverSelector: cover },
  );
  if (edge === "top") {
    expect(result.top, JSON.stringify(result)).toBeGreaterThanOrEqual(
      result.barBottom - 1,
    );
  } else {
    expect(result.bottom, JSON.stringify(result)).toBeLessThanOrEqual(
      result.barTop + 1,
    );
  }
  expect(result.hitsTarget, JSON.stringify(result)).toBe(true);
}
