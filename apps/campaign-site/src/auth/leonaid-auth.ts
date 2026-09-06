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

// The pinned upstream seam resolves metadata.cmsUserId rather than email.
// The outer middleware still closes every route except read-only auth/me.
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
