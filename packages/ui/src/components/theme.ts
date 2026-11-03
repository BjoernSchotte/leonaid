/**
 * Theme preference helpers: <html data-theme>, the stored choice and the
 * light/dark toggle (shell button, shift+t, palette commands).
 */

export type ThemeMode = "system" | "light" | "dark";

const storageKey = "leonaid.theme";

/** The stored preference ("system" when none or storage is blocked). */
export function storedTheme(): ThemeMode {
  try {
    const value = window.localStorage.getItem(storageKey);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

function isDarkSystemTheme(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
}

/** Sets data-theme on <html> as theme-init.js does before the first paint. */
export function applyTheme(mode: ThemeMode) {
  const resolved =
    mode === "system" ? (isDarkSystemTheme() ? "dark" : "light") : mode;
  document.documentElement.dataset.theme = resolved;
  document.documentElement.dataset.themePreference = mode;
  document.documentElement.style.colorScheme = resolved;
}

/** Applies and stores a preference; storage failures keep it per session. */
export function setThemePreference(mode: ThemeMode) {
  applyTheme(mode);
  try {
    window.localStorage.setItem(storageKey, mode);
  } catch {
    // Theme selection still applies for this session when storage is blocked.
  }
}

/** The theme currently shown, from the <html> attribute. */
export function resolvedTheme(): "light" | "dark" {
  const current = document.documentElement.dataset.theme;
  if (current === "light" || current === "dark") return current;
  return isDarkSystemTheme() ? "dark" : "light";
}

/** Switches between light and dark and stores the choice. */
export function toggleTheme(): "light" | "dark" {
  const next = resolvedTheme() === "dark" ? "light" : "dark";
  setThemePreference(next);
  return next;
}
