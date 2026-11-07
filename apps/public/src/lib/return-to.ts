import { ADMIN_BASE, PWA_BASE } from "@leonaid/ui/base-paths";

/** Keep login navigation same-origin, including after URL decoding/normalizing. */
export function safeLocalReturnTo(value: string, fallback: string): string {
  let decoded = value;
  for (let depth = 0; depth < 5; depth += 1) {
    if (
      !decoded.startsWith("/") ||
      decoded.startsWith("//") ||
      /[\\\u0000-\u0020\u007f]/.test(decoded)
    )
      return fallback;
    try {
      if (
        new URL(decoded, "https://leonaid.invalid").origin !==
        "https://leonaid.invalid"
      )
        return fallback;
      const next = decodeURIComponent(decoded);
      if (next === decoded) return value;
      decoded = next;
    } catch {
      return fallback;
    }
  }
  return fallback;
}

// The CMS editor signs in through the same page (apps/campaign-site).
const CMS_ADMIN_BASE = "/_emdash/admin/";

/**
 * A deep link into a member app survives the login (specs/multi-domain §6.7,
 * §9.5): same-origin, and below the admin base, the PWA base or the CMS
 * editor. Anything else falls back.
 */
export function memberReturnTo(value: string, fallback: string): string {
  const local = safeLocalReturnTo(value, fallback);
  if (local === fallback) return fallback;
  const path = local.split(/[?#]/, 1)[0] ?? "";
  const allowed = [ADMIN_BASE, PWA_BASE, CMS_ADMIN_BASE].some(
    (base) => path === base.slice(0, -1) || path.startsWith(base),
  );
  return allowed ? local : fallback;
}
