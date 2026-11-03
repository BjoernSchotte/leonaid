import type { AtRule, PluginCreator } from "postcss";

/** Container name of the PWA's 480 px content column (`.pwa-main`). */
export const COLUMN_CONTAINER = "pwa-column";

const WIDTH_FEATURE = String.raw`\(\s*(?:min|max)-width\s*:\s*[\d.]+(?:px|rem|em)\s*\)`;
const WIDTH_ONLY = new RegExp(
  String.raw`^\s*${WIDTH_FEATURE}(?:\s+and\s+${WIDTH_FEATURE})*\s*$`,
  "i",
);

/** True for a media condition made only of min-/max-width features. */
export function isWidthOnlyMedia(params: string): boolean {
  return WIDTH_ONLY.test(params);
}

/**
 * The PWA renders shared pages in a column of at most 480 px, also on wide
 * screens. Shared CSS sizes its layouts by viewport width, so in the PWA
 * bundle every width-only `@media` becomes an `@container` query on the
 * column: pages get their phone layout and 44 px touch targets at any
 * window width. A list such as `(pointer: coarse), (max-width: 760px)`
 * keeps its other conditions as @media. Queries that must stay on the viewport add a media type
 * (`@media screen and (min-width: …)`) and are left alone.
 */
export const columnQueries: PluginCreator<void> = () => ({
  postcssPlugin: "leonaid-pwa-column-queries",
  AtRule: {
    media(rule: AtRule) {
      const parts = rule.params.split(",").map((part) => part.trim());
      const width = parts.filter(isWidthOnlyMedia);
      if (!width.length) return;
      const rest = parts.filter((part) => !isWidthOnlyMedia(part));
      // One @container per width condition; a list means "any of them".
      const containers = width.map((condition) =>
        rule.clone({
          name: "container",
          params: `${COLUMN_CONTAINER} ${condition}`,
        }),
      );
      rule.after(containers);
      if (rest.length) rule.params = rest.join(", ");
      else rule.remove();
    },
  },
});
columnQueries.postcss = true;
