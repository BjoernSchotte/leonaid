import type { AtRule, PluginCreator } from "postcss";

/** Container name of the PWA's 480 px content column (`.pwa-main`). */
export const COLUMN_CONTAINER = "pwa-column";

type WidthBound = "max" | "min" | "range";

const LENGTH = String.raw`[\d.]+(?:px|rem|em)`;
const FEATURES: readonly [RegExp, WidthBound][] = [
  [new RegExp(String.raw`^\(\s*max-width\s*:\s*${LENGTH}\s*\)$`, "i"), "max"],
  [new RegExp(String.raw`^\(\s*min-width\s*:\s*${LENGTH}\s*\)$`, "i"), "min"],
  // Range syntax as Tailwind v4 and lightningcss write it.
  [new RegExp(String.raw`^\(\s*width\s*<=?\s*${LENGTH}\s*\)$`, "i"), "max"],
  [new RegExp(String.raw`^\(\s*${LENGTH}\s*>=?\s*width\s*\)$`, "i"), "max"],
  [new RegExp(String.raw`^\(\s*width\s*>=?\s*${LENGTH}\s*\)$`, "i"), "min"],
  [new RegExp(String.raw`^\(\s*${LENGTH}\s*<=?\s*width\s*\)$`, "i"), "min"],
  [
    new RegExp(
      String.raw`^\(\s*${LENGTH}\s*<=?\s*width\s*<=?\s*${LENGTH}\s*\)$`,
      "i",
    ),
    "range",
  ],
];

/**
 * Classifies one media condition (no commas). Returns null unless it is made
 * only of width features: a media type (`screen and …`), `not`, `only` or
 * any other feature keeps the query on the viewport.
 */
export function widthCondition(condition: string): "max" | "other" | null {
  const parts = condition.trim().split(/\s+and\s+/i);
  const bounds: WidthBound[] = [];
  for (const part of parts) {
    const match = FEATURES.find(([pattern]) => pattern.test(part.trim()));
    if (!match) return null;
    bounds.push(match[1]);
  }
  return bounds.every((bound) => bound === "max") ? "max" : "other";
}

/** True for a media condition made only of min-/max-width features. */
export function isWidthOnlyMedia(condition: string): boolean {
  return widthCondition(condition) !== null;
}

/**
 * The PWA renders shared pages in a column of at most 480 px, also on wide
 * screens, but shared CSS sizes layouts by viewport width. In the PWA bundle
 * every width-only `@media` condition gets an `@container` copy on the
 * column, so pages get their phone layout at any window width.
 *
 * - Upper bounds only (`max-width`, `width <= …`): the `@media` stays and
 *   the `@container` copy follows it. Overlays outside the column (toasts,
 *   dialogs, the sheet) keep their phone rules on phones; inside the column
 *   the copy matches whenever the viewport rule could.
 * - Lower bounds or ranges: container only, since the viewport is wider
 *   than the column and would pick the desktop layout.
 * - A list such as `(pointer: coarse), (max-width: 760px)` keeps its other
 *   conditions as `@media`.
 *
 * To keep a query on the viewport only, give it a media type:
 * `@media screen and (min-width: …)`.
 */
export const columnQueries: PluginCreator<void> = () => ({
  postcssPlugin: "leonaid-pwa-column-queries",
  prepare() {
    // PostCSS revisits changed nodes; rewrite each @media once.
    const done = new WeakSet<AtRule>();
    return {
      AtRule: {
        media(rule: AtRule) {
          if (done.has(rule)) return;
          done.add(rule);
          const conditions = splitList(rule.params);
          const kinds = conditions.map(widthCondition);
          if (kinds.every((kind) => kind === null)) return;
          const viewport = conditions.filter(
            (_, index) => kinds[index] !== "other",
          );
          const container = conditions.filter(
            (_, index) => kinds[index] !== null,
          );
          rule.after(
            container.map((condition) =>
              rule.clone({
                name: "container",
                params: `${COLUMN_CONTAINER} ${condition}`,
              }),
            ),
          );
          if (viewport.length) rule.params = viewport.join(", ");
          else rule.remove();
        },
      },
    };
  },
});
columnQueries.postcss = true;

/** Splits a media query list on top-level commas. */
function splitList(params: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let current = "";
  for (const character of params) {
    if (character === "(") depth += 1;
    if (character === ")") depth -= 1;
    if (character === "," && depth === 0) {
      parts.push(current.trim());
      current = "";
    } else {
      current += character;
    }
  }
  if (current.trim()) parts.push(current.trim());
  return parts;
}
