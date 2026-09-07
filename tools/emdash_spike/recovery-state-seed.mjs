import { writeFile } from "node:fs/promises";
import {
  armBootstrap,
  consumeBootstrap,
  completeBootstrap,
  requireCompletedBootstrap,
  bootstrapIsArmed,
} from "../../apps/campaign-site/src/bootstrap-control.mjs";
import assert from "node:assert/strict";

const actor = "10000000-0000-4000-8000-000000000001";
if (process.argv[2] === "seed") {
  await armBootstrap("/bootstrap", actor);
  await consumeBootstrap("/bootstrap", actor);
  await completeBootstrap("/bootstrap", actor);
  await writeFile(
    "/twenty-storage/recovery-proof.txt",
    "synthetic CRM storage",
  );
} else {
  assert.equal(process.argv[2], "verify");
}
await requireCompletedBootstrap("/bootstrap");
assert.equal(await bootstrapIsArmed("/bootstrap"), false);
console.log("recovery-state: durable completed bootstrap remains closed");
