// Applies the stored colour theme before the first paint. It is a blocking
// classic script loaded from a file (not inline), so the Content-Security-Policy
// keeps script-src at 'self' without 'unsafe-inline'.
try {
  const preference = localStorage.getItem("leonaid.theme") ?? "system";
  const resolved =
    preference === "system"
      ? matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"
      : preference;
  document.documentElement.dataset.theme = resolved;
  document.documentElement.dataset.themePreference = preference;
  document.documentElement.style.colorScheme = resolved;
} catch {}
