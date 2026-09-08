import assert from "node:assert/strict";
import { access, writeFile, rename } from "node:fs/promises";
import { expect } from "@playwright/test";

function path(label, stage) {
  assert.match(
    label,
    /^(deadline-(chromium|firefox|webkit)-(native|js)-person|partial-(chromium|firefox|webkit)-native-new-company)$/,
  );
  assert.ok(
    [
      "locked",
      "submitted",
      "timeout",
      "released",
      "accepted",
      "replay-ready",
      "replayed",
      "verified",
    ].includes(stage),
  );
  return `/proof/${label}-${stage}`;
}
export async function deadlineWait(label, stage) {
  await expect
    .poll(
      async () => {
        try {
          await access(path(label, stage));
          return true;
        } catch (error) {
          if (error.code === "ENOENT") return false;
          throw error;
        }
      },
      { timeout: 180000 },
    )
    .toBe(true);
}
export async function deadlineSignal(label, stage, value = {}) {
  const target = path(label, stage);
  await writeFile(`${target}.tmp`, JSON.stringify(value), {
    flag: "wx",
    // Dedicated directory beneath the private test root; only synthetic
    // command/reference markers, never tokens. The controller uses host UID.
    mode: 0o644,
  });
  await rename(`${target}.tmp`, target);
}
