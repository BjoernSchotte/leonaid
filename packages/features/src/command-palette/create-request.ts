/**
 * "Anlegen" entries of the palette open a page with `?create=<kind>`; the
 * page starts its own create form (focuses the field, opens the panel).
 * The page still uses its normal, server-authorized create request.
 */
export const CREATE_PARAMETER = "create";

export function createHref(path: string, kind: string): string {
  const [base, query = ""] = path.split("?", 2);
  const parameters = new URLSearchParams(query);
  parameters.set(CREATE_PARAMETER, kind);
  return `${base}?${parameters.toString()}`;
}

/**
 * True once when the URL asks for `kind`; the parameter is removed without a
 * history entry, so a reload does not reopen the form.
 */
export function consumeCreateRequest(kind: string): boolean {
  if (typeof window === "undefined") return false;
  const url = new URL(window.location.href);
  if (url.searchParams.get(CREATE_PARAMETER) !== kind) return false;
  url.searchParams.delete(CREATE_PARAMETER);
  window.history.replaceState(window.history.state, "", url);
  return true;
}
