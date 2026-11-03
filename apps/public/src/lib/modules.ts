// Mirrors LEONAID_DISABLED_MODULES of the Core API (comma-separated module
// IDs). A switched-off module also disappears from the public pages, so no
// form posts to an API route that answers 404.
export function moduleEnabled(
  id: string,
  raw: string | undefined = process.env.LEONAID_DISABLED_MODULES,
): boolean {
  const disabled = (raw ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  return !disabled.includes(id);
}
