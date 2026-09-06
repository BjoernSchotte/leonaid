import pg from "pg";
import { CoreIdentityError, readCoreIdentity } from "./core-identity";
import { synchronizeExternalIdentity } from "./identity-map.mjs";
import { requireCompletedBootstrap } from "../bootstrap-control.mjs";
import { setupIsComplete } from "../database-ready";

const pool = new pg.Pool({
  max: 5,
  connectionTimeoutMillis: 2000,
  query_timeout: 3000,
  idleTimeoutMillis: 5000,
});
pool.on("error", () => {});

// The pinned upstream seam resolves metadata.cmsUserId rather than email.
// Route and campaign authorization remain separate from identity provisioning.
export async function authenticate(request: Request) {
  const identity = await readCoreIdentity(request);
  if (identity.role === 40) {
    // A Charity identity can never bootstrap the CMS or enter half-setup state.
    try {
      await requireCompletedBootstrap("/app/bootstrap-state");
    } catch {
      throw new CoreIdentityError(403);
    }
    if (!(await setupIsComplete())) throw new CoreIdentityError(503);
  }
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
