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
        // Sticky or fixed parts (bars, jump navs) do not scroll: skip them.
        const pinned = (element) => {
          for (
            let node = element;
            node && node !== document.body;
            node = node.parentElement
          ) {
            const position = getComputedStyle(node).position;
            if (position === "sticky" || position === "fixed") return true;
          }
          return false;
        };
        if (pinned(target) || pinned(before)) continue;
        const box = target.getBoundingClientRect();
        const top = box.top + window.scrollY;
        if (box.height === 0 || box.height > 120) continue;
        // The page must be able to scroll the target half under the bar:
        // past the top bar for "top", up from below the fold for "bottom".
        const maxScroll = scrollHeight - window.innerHeight;
        const needed =
          edge === "top"
            ? top - (coverBottom - box.height / 2)
            : top + box.height / 2 - coverTop;
        if (needed <= box.height || needed > maxScroll) continue;
        document
          .querySelectorAll("[data-obscure-target], [data-obscure-before]")
          .forEach((element) => {
            delete element.dataset.obscureTarget;
            delete element.dataset.obscureBefore;
          });
        target.dataset.obscureTarget = "";
        before.dataset.obscureBefore = "";
        before.focus({ preventScroll: true });
        return { found: true };
      }
      const inScope = tabbables.filter((element) => element.closest(scope));
      return {
        found: false,
        tabbables: tabbables.length,
        inScope: inScope.length,
        lastTop: inScope.length
          ? inScope.at(-1).getBoundingClientRect().top + window.scrollY
          : null,
        innerHeight: window.innerHeight,
        scrollHeight,
      };
    },
    {
      scope,
      edge,
      coverTop: coverBox.y,
      coverBottom: coverBox.y + coverBox.height,
    },
  );
  expect(
    prepared.found,
    `a tabbable pair below the fold in ${scope}: ${JSON.stringify(prepared)}`,
  ).toBe(true);
  // Let the shell's focus reveal for the element before settle, then park
  // the target half under the bar: still "in the viewport", so without
  // scroll-padding a browser does not scroll on focus. Instant scrolling:
  // the page sets scroll-behavior: smooth.
  await page.waitForTimeout(500);
  const parked = await page.evaluate(
    ({ edge, coverTop, coverBottom }) => {
      const element = document.querySelector("[data-obscure-target]");
      const fromY = window.scrollY;
      // A few rounds: sticky headers that start or stop sticking can shift
      // the layout while scrolling.
      for (let round = 0; round < 4; round += 1) {
        const now = element.getBoundingClientRect();
        const delta =
          edge === "top"
            ? now.top - (coverBottom - now.height / 2)
            : now.bottom - (coverTop + now.height / 2);
        if (Math.abs(delta) < 1) break;
        window.scrollBy({ top: delta, behavior: "instant" });
      }
      return {
        fromY,
        toY: window.scrollY,
        maxY: document.documentElement.scrollHeight - window.innerHeight,
        top: element.getBoundingClientRect().top,
        active: document.activeElement?.tagName,
      };
    },
    { edge, coverTop: coverBox.y, coverBottom: coverBox.y + coverBox.height },
  );
  const target = page.locator("[data-obscure-target]");
  const startBox = await target.boundingBox();
  if (edge === "top") {
    expect(
      startBox.y,
      `the target starts under the bar: ${JSON.stringify(parked)}`,
    ).toBeLessThan(coverBox.y + coverBox.height);
  } else {
    expect(startBox.y + startBox.height).toBeGreaterThan(coverBox.y);
  }

  await page.keyboard.press("Tab");
  await expect(target).toBeFocused();
  const measure = () =>
    target.evaluate(
      (element, { coverSelector }) => {
        const box = element.getBoundingClientRect();
        const bar = document
          .querySelector(coverSelector)
          .getBoundingClientRect();
        const hit = document.elementFromPoint(
          box.left + Math.min(box.width / 2, 20),
          box.top + box.height / 2,
        );
        return {
          top: box.top,
          bottom: box.bottom,
          barTop: bar.top,
          barBottom: bar.bottom,
          hitsTarget: Boolean(
            hit && (hit === element || element.contains(hit)),
          ),
          hit: hit
            ? `${hit.tagName.toLowerCase()}.${[...hit.classList].join(".")}`
            : null,
          target: `${element.tagName.toLowerCase()}.${[...element.classList].join(".")} ${(element.textContent ?? "").trim().slice(0, 30)}`,
        };
      },
      { coverSelector: cover },
    );
  // The focused element must end up clear: the browser's (smooth) focus
  // scroll, and the shell's reveal where the browser ignores scroll-padding.
  // Received shows the last measurement when it never gets clear.
  await expect
    .poll(
      async () => {
        const result = await measure();
        const clear =
          edge === "top"
            ? result.top >= result.barBottom - 1
            : result.bottom <= result.barTop + 1;
        return clear && result.hitsTarget ? "clear" : JSON.stringify(result);
      },
      { timeout: 3000 },
    )
    .toBe("clear");
}
