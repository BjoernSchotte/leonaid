import pg from "pg";
import { CoreIdentityError, readCoreIdentity } from "./core-identity";
import { synchronizeExternalIdentity } from "./identity-map.mjs";

const pool = new pg.Pool({
  max: 5,
  connectionTimeoutMillis: 2000,
  query_timeout: 3000,
  idleTimeoutMillis: 5000,
});
pool.on("error", () => {});

// This adapter is not enabled in astro.config until the stable-ID upstream seam
// and protected bootstrap are proven. Stock email-based lookup is unsafe.
export async function authenticate(request: Request) {
  const identity = await readCoreIdentity(request);
  // Charity access remains disabled until the campaign-isolation gate passes.
  if (identity.role !== 50) throw new CoreIdentityError(403);
  try {
    const mapped = await synchronizeExternalIdentity(pool, {
      coreUserId: identity.userId,
      email: identity.email,
      name: identity.displayName,
      role: identity.role,
    });
    return {
      email: identity.email,
      name: identity.displayName,
      role: identity.role,
      subject: identity.userId,
      metadata: { cmsUserId: mapped.cmsUserId },
    };
  } catch {
    throw new CoreIdentityError(503);
  }
}
