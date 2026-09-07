import { lstat, mkdir } from "node:fs/promises";

const marker = "/app/bootstrap-state/cms-maintenance";

// A durable, operator-owned close-only gate. An unreadable or malformed marker
// fails closed. No HTTP request, migration or process restart removes it.
export async function cmsMaintenanceClosed() {
  try {
    await lstat(marker);
    return true;
  } catch (error) {
    return error.code !== "ENOENT";
  }
}

export async function closeCmsTraffic() {
  try {
    await mkdir(marker, { mode: 0o700 });
  } catch (error) {
    if (error.code !== "EEXIST") throw error;
  }
  const state = await lstat(marker);
  if (!state.isDirectory() || state.isSymbolicLink())
    throw new Error("cms_maintenance_marker_invalid");
}
