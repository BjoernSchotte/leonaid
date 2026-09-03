import type { PublicActionRouteResponse } from "@leonaid/api-client";

// Presentation only: no new action capabilities or backend configuration.
// Use the immutable archive slug so alias and archive share the same identity.
export function isKrapfentaxiAction(
  route: PublicActionRouteResponse | null,
): boolean {
  return /^krapfentaxi(?:-|$)/.test(route?.action?.archiveSlug ?? "");
}
