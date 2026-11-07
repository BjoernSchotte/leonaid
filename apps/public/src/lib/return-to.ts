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

const ORIGIN = "https://leonaid.invalid";

/**
 * A deep link into a member app survives the login (specs/multi-domain §6.7,
 * §9.5): same-origin, and below the admin base, the PWA base or the CMS
 * editor. Anything else falls back.
 *
 * The check runs on the path the browser will open: the URL parser resolves
 * dot segments, also encoded ones, so "/app/../campaigns/x/" is the public
 * page "/campaigns/x/" and falls back. The result is that resolved path.
 */
export function memberReturnTo(value: string, fallback: string): string {
  const local = safeLocalReturnTo(value, fallback);
  if (local === fallback) return fallback;
  let target: URL;
  try {
    target = new URL(local, ORIGIN);
  } catch {
    return fallback;
  }
  if (target.origin !== ORIGIN) return fallback;
  const path = target.pathname;
  const allowed = [ADMIN_BASE, PWA_BASE, CMS_ADMIN_BASE].some(
    (base) => path === base.slice(0, -1) || path.startsWith(base),
  );
  return allowed ? path + target.search + target.hash : fallback;
}
