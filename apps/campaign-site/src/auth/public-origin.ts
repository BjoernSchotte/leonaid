// Only the private Caddy ingress may supply these headers. Caddy overwrites
// forwarding headers; no CMS port is published. Identity never comes from them.
export function hasSecurePublicOrigin(request: Request): boolean {
  try {
    const origin = new URL(process.env.EMDASH_SITE_URL ?? "");
    if (
      origin.protocol !== "https:" ||
      origin.username ||
      origin.password ||
      origin.pathname !== "/" ||
      origin.search ||
      origin.hash
    )
      return false;
    if (
      request.headers.get("host") !== origin.host ||
      request.headers.get("x-forwarded-host") !== origin.host ||
      request.headers.get("x-forwarded-proto") !== "https" ||
      request.headers.has("forwarded")
    )
      return false;
    const supplied = request.headers.get("origin");
    if (supplied !== null && supplied !== origin.origin) return false;
    if (!["GET", "HEAD"].includes(request.method) && supplied !== origin.origin)
      return false;
    return true;
  } catch {
    return false;
  }
}
