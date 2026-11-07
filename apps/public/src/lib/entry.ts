import { memberReturnTo } from "./return-to";

/**
 * The entry redirects only to Core's landingPath, and only when it is a
 * same-origin path below a member app (specs/multi-domain §9.5).
 */
export function entryDestination(
  landingPath: unknown,
  fallback: string,
): string {
  return typeof landingPath === "string"
    ? memberReturnTo(landingPath, fallback)
    : fallback;
}
