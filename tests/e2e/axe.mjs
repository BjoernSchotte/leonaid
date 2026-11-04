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
  await settleAnimations(page);
  let builder = new AxeBuilder({ page });
  if (include) builder = builder.include(include);
  if (tags) builder = builder.withTags([...tags]);
  return builder.analyze();
}
