/**
 * The public origin of a request behind the proxy: Caddy terminates TLS and
 * forwards X-Forwarded-Proto, so the scheme comes from there when present.
 */
export function requestOrigin(request: Request, url: URL): URL {
  const forwardedProtocol = request.headers
    .get("x-forwarded-proto")
    ?.split(",", 1)[0]
    ?.trim();
  const origin = new URL(url.origin);
  if (forwardedProtocol === "http" || forwardedProtocol === "https") {
    origin.protocol = `${forwardedProtocol}:`;
  }
  return origin;
}
