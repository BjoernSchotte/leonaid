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
  // A page behind another one (axe analyzes in a temporary page) does not
  // advance its animation clock, so a fade there never finishes.
  await page.bringToFront();
  const stuck = await page.evaluate(async () => {
    const running = document.getAnimations().filter((animation) => {
      const timing = animation.effect?.getComputedTiming();
      // Paused, idle or rate-0 animations never finish; only running finite
      // ones with a nonzero playback rate end.
      return (
        animation.playState === "running" &&
        animation.playbackRate !== 0 &&
        Number.isFinite(timing?.endTime)
      );
    });
    const remaining = running.map((animation) => {
      const timing = animation.effect.getComputedTiming();
      const rate = animation.playbackRate;
      const local = timing.localTime ?? 0;
      // Forwards it finishes at endTime, backwards (rate < 0) at time 0.
      return rate > 0 ? (timing.endTime - local) / rate : local / -rate;
    });
    const limit = Math.max(0, ...remaining) + 2000;
    const settled = await Promise.race([
      Promise.all(
        running.map((animation) => animation.finished.catch(() => undefined)),
      ).then(() => true),
      new Promise((resolve) => setTimeout(() => resolve(false), limit)),
    ]);
    if (settled) return [];
    return running
      .filter((animation) => animation.playState === "running")
      .map(
        (animation) =>
          `${animation.animationName || animation.constructor.name} on ${animation.effect?.target?.tagName?.toLowerCase() ?? "?"}.${animation.effect?.target?.className ?? ""}`,
      );
  });
  if (stuck.length)
    throw new Error(`Animations did not finish: ${stuck.join(", ")}`);
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
