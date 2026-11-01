import { krapfentaxiTheme } from "./krapfentaxi";
import { leonaidTheme } from "./leonaid";
import type { PublicTheme } from "./types";

export type { PublicTheme, ThemeNavigationItem } from "./types";

// Theme registry. Adding a theme means adding themes/<key>/index.ts (with an
// optional theme.css scoped by its body class and an optional Intro) and
// registering it here. The key is then selected as data through an action's
// presentationTheme or the CMS theme field.
const themes: ReadonlyMap<string, PublicTheme> = new Map(
  [leonaidTheme, krapfentaxiTheme].map((theme) => [theme.key, theme]),
);

export const defaultTheme = leonaidTheme;

export function hasPublicTheme(key: string): boolean {
  return themes.has(key);
}

/** Resolve a theme key from data; unknown or missing keys fall back. */
export function resolvePublicTheme(
  key: string | null | undefined,
): PublicTheme {
  return (key ? themes.get(key) : undefined) ?? defaultTheme;
}
