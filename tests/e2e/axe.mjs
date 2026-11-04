// Shared axe scan for the browser specs: waits for running finite
// animations, then runs AxeBuilder on the real page.
//
// Why the wait: popovers fade in and modals rise (opacity) over 120–180 ms.
// axe blends text and ground with the current opacity, so a scan during a
// fade reports colour pairs far below their real contrast (the list view's
// filter label measured 4.39:1 mid-fade, 14.5:1 at rest). Endless
// animations (spinners, skeleton shimmer) never finish and are skipped.
import AxeBuilder from "@axe-core/playwright";

/** WCAG 2.2 AA rule tags (specs without tags run every axe rule). */
export const WCAG_TAGS = Object.freeze([
  "wcag2a",
  "wcag2aa",
  "wcag21aa",
  "wcag22aa",
]);

const SCRIPT_PROBE_MS = 2000;

/**
 * axe-core needs the page's task queue. In a context with JavaScript
 * disabled, evaluate still runs but timers never fire, so axe would hang
 * until the test timeout. A zero-delay timer probe fails fast instead.
 */
export async function assertPageScriptsRun(page) {
  let timer;
  const ran = await Promise.race([
    page.evaluate(
      () => new Promise((resolve) => setTimeout(() => resolve(true), 0)),
    ),
    new Promise((resolve) => {
      timer = setTimeout(() => resolve(false), SCRIPT_PROBE_MS);
    }),
  ]).finally(() => clearTimeout(timer));
  if (!ran) {
    throw new Error(
      "analyzeAccessibility: page timers do not run (JavaScript disabled in " +
        "this browser context?); axe-core cannot finish there. Scan in a " +
        "context with JavaScript enabled.",
    );
  }
}

export async function settleAnimations(page) {
  await page.evaluate(() =>
    Promise.all(
      document
        .getAnimations()
        .filter((animation) =>
          Number.isFinite(animation.effect?.getComputedTiming().endTime),
        )
        .map((animation) => animation.finished.catch(() => undefined)),
    ),
  );
}

/**
 * Runs axe on `page` after animations settle and returns its results.
 * - `include`: a selector that limits the scan to one region.
 * - `tags`: rule tags (e.g. `WCAG_TAGS`); without them axe runs every rule,
 *   as `new AxeBuilder({ page }).analyze()` does.
 */
export async function analyzeAccessibility(page, { include, tags } = {}) {
  await assertPageScriptsRun(page);
  await settleAnimations(page);
  let builder = new AxeBuilder({ page });
  if (include) builder = builder.include(include);
  if (tags) builder = builder.withTags([...tags]);
  return builder.analyze();
}
