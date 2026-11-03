import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import postcss from "postcss";
import { describe, expect, it } from "vitest";

import {
  columnQueries,
  isWidthOnlyMedia,
  widthCondition,
} from "./column-queries";

function rewrite(css: string): string {
  return postcss([columnQueries()]).process(css, { from: undefined }).css;
}

/** Normalised at-rule headers in output order, e.g. "@media (x)". */
function headers(css: string): string[] {
  const root = postcss.parse(rewrite(css));
  const found: string[] = [];
  root.walkAtRules((rule) => {
    found.push(`@${rule.name} ${rule.params}`);
  });
  return found;
}

describe("widthCondition", () => {
  it.each([
    ["(max-width: 800px)", "max"],
    ["(MAX-WIDTH: 800PX)", "max"],
    ["(max-width: 50rem) and (max-width: 900px)", "max"],
    ["(width <= 800px)", "max"],
    ["(width < 48em)", "max"],
    ["(800px >= width)", "max"],
    ["(min-width: 660px)", "other"],
    ["(width >= 40rem)", "other"],
    ["(max-width: 1100px) and (min-width: 701px)", "other"],
    ["(400px <= width <= 800px)", "other"],
  ] as const)("%s is %s", (condition, kind) => {
    expect(widthCondition(condition)).toBe(kind);
    expect(isWidthOnlyMedia(condition)).toBe(true);
  });

  it.each([
    "screen and (min-width: 560px)",
    "only screen and (max-width: 800px)",
    "not all and (max-width: 800px)",
    "print",
    "(prefers-reduced-motion: reduce)",
    "(hover: none) and (pointer: coarse)",
    "(max-height: 600px)",
    "(max-width: 800px) and (orientation: portrait)",
  ])("leaves %s on the viewport", (condition) => {
    expect(widthCondition(condition)).toBeNull();
  });
});

describe("columnQueries", () => {
  it("keeps an upper bound on the viewport and adds the column copy after it", () => {
    const css = rewrite(
      ".a{color:red}@media (max-width: 800px){.btn{min-height:44px}}.b{color:blue}",
    );
    expect(css).toBe(
      ".a{color:red}@media (max-width: 800px){.btn{min-height:44px}}@container pwa-column (max-width: 800px){.btn{min-height:44px}}.b{color:blue}",
    );
  });

  it("moves lower bounds and ranges to the column only", () => {
    expect(headers("@media (min-width: 660px){.a{x:1}}")).toEqual([
      "@container pwa-column (min-width: 660px)",
    ]);
    expect(
      headers("@media (max-width: 1100px) and (min-width: 701px){.a{x:1}}"),
    ).toEqual([
      "@container pwa-column (max-width: 1100px) and (min-width: 701px)",
    ]);
    expect(headers("@media (width >= 40rem){.a{x:1}}")).toEqual([
      "@container pwa-column (width >= 40rem)",
    ]);
  });

  it("leaves non-width queries and the screen opt-out untouched", () => {
    const css =
      "@media screen and (min-width: 560px){.pwa{box-shadow:none}}@media (prefers-reduced-motion: reduce){*{animation:none}}@media (pointer: coarse){.a{x:1}}";
    expect(rewrite(css)).toBe(css);
  });

  it("splits a mixed list", () => {
    expect(
      headers("@media (pointer: coarse), (max-width: 760px){.a{x:1}}"),
    ).toEqual([
      "@media (pointer: coarse), (max-width: 760px)",
      "@container pwa-column (max-width: 760px)",
    ]);
    expect(
      headers("@media (pointer: coarse), (min-width: 900px){.a{x:1}}"),
    ).toEqual([
      "@media (pointer: coarse)",
      "@container pwa-column (min-width: 900px)",
    ]);
  });

  it("rewrites queries nested in @supports and in rules", () => {
    expect(
      headers(
        "@supports (display: grid){@media (max-width: 600px){.a{x:1}}}.b{@media (min-width: 700px){color:red}}",
      ),
    ).toEqual([
      "@supports (display: grid)",
      "@media (max-width: 600px)",
      "@container pwa-column (max-width: 600px)",
      "@container pwa-column (min-width: 700px)",
    ]);
  });

  it("copies a rule once, also when PostCSS revisits it", () => {
    const css = rewrite(
      "@media (max-width: 800px){.a{x:1}@media (min-width: 400px){.b{y:2}}}",
    );
    expect(css.match(/@container/g)).toHaveLength(3);
    expect(css.match(/@media/g)).toHaveLength(1);
  });

  it("keeps the phone rules of overlays outside the column (toast, buttons)", () => {
    const styles = resolve(
      __dirname,
      "../../packages/ui/src/styles/components",
    );
    for (const [file, selector] of [
      ["toast.css", ".toast-close"],
      ["button.css", ".btn-icon"],
    ] as const) {
      const root = postcss.parse(
        rewrite(readFileSync(resolve(styles, file), "utf8")),
      );
      const kept: string[] = [];
      root.walkAtRules("media", (rule) => {
        if (/max-width:\s*800px/.test(rule.params)) {
          rule.walkRules((inner) => {
            kept.push(inner.selector);
          });
        }
      });
      expect(kept.join(" "), file).toContain(selector);
    }
  });
});
