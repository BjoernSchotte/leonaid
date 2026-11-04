import { useEffect, useState } from "react";

/**
 * Leitsystem tokens as concrete colours. A canvas cannot read `var()`, and
 * our tokens use `oklch()`/`calc()`, so a probe element resolves them.
 */
export interface ChartTheme {
  /** Single series: the zone hue of the surrounding `[data-zone]`. */
  readonly zone: string;
  /** Track behind a single series. */
  readonly track: string;
  readonly text: string;
  readonly text2: string;
  readonly border: string;
  readonly surface: string;
  /** Diverging ramp, negative pole to positive pole (5 steps). */
  readonly diverging: readonly [string, string, string, string, string];
  readonly font: string;
}

const cache = new Map<string, ChartTheme>();

/**
 * The theme for a chart host, resolved once per theme and zone (M9): the
 * key is <html data-theme>, the OS scheme and the host's data-zone.
 */
export function themeFor(host: HTMLElement): ChartTheme {
  const key = [
    document.documentElement.getAttribute("data-theme") ?? "",
    window.matchMedia?.("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light",
    host.closest("[data-zone]")?.getAttribute("data-zone") ?? "",
  ].join("|");
  let theme = cache.get(key);
  if (!theme) {
    theme = resolveTheme(host);
    cache.set(key, theme);
  }
  return theme;
}

export function resolveTheme(host: HTMLElement): ChartTheme {
  /*
   * One fresh probe per token, transitions off: reusing one probe would
   * start a colour transition from the previous token, and reading right
   * away returns that start colour (all tokens would read as the first).
   */
  const read = (token: string) => {
    const probe = document.createElement("span");
    probe.setAttribute("aria-hidden", "true");
    probe.style.setProperty("transition", "none");
    probe.style.setProperty("color", `var(${token})`);
    host.append(probe);
    const color = getComputedStyle(probe).color;
    probe.remove();
    return color;
  };
  return {
    zone: read("--zone"),
    track: read("--surface-3"),
    text: read("--text"),
    text2: read("--text-2"),
    border: read("--border"),
    surface: read("--surface"),
    diverging: [
      read("--chart-neg"),
      read("--chart-neg-soft"),
      read("--chart-mid"),
      read("--chart-pos-soft"),
      read("--chart-pos"),
    ],
    font: getComputedStyle(host).fontFamily,
  };
}

/** Bumps when the theme changes: `<html data-theme>` or the OS scheme. */
export function useThemeVersion(): number {
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const bump = () => setVersion((value) => value + 1);
    const observer = new MutationObserver(bump);
    observer.observe(document.documentElement, {
      attributeFilter: ["data-theme"],
    });
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    media?.addEventListener("change", bump);
    return () => {
      observer.disconnect();
      media?.removeEventListener("change", bump);
    };
  }, []);
  return version;
}

export type DivergingStep = "pos" | "pos-soft" | "mid" | "neg-soft" | "neg";

const STEPS: readonly DivergingStep[] = [
  "pos",
  "pos-soft",
  "mid",
  "neg-soft",
  "neg",
];

/**
 * Ramp steps for `count` ordered segments: the first takes the positive
 * pole, the last the negative, a middle one (odd counts) the grey.
 */
export function divergingSteps(count: number): DivergingStep[] {
  const fixed: Record<number, DivergingStep[]> = {
    1: ["mid"],
    2: ["pos", "neg"],
    3: ["pos", "mid", "neg"],
    4: ["pos", "pos-soft", "neg-soft", "neg"],
    5: ["pos", "pos-soft", "mid", "neg-soft", "neg"],
  };
  return (
    fixed[count] ??
    // More segments: spread the five steps over them in order.
    Array.from(
      { length: count },
      (_, index) => STEPS[Math.round((index / (count - 1)) * 4)]!,
    )
  );
}

export function divergingColors(theme: ChartTheme, count: number): string[] {
  const [neg, negSoft, mid, posSoft, pos] = theme.diverging;
  const color: Record<DivergingStep, string> = {
    pos,
    "pos-soft": posSoft,
    mid,
    "neg-soft": negSoft,
    neg,
  };
  return divergingSteps(count).map((step) => color[step]);
}
