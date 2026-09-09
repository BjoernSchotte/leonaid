import assert from "node:assert/strict";
import { mkdtemp, readFile, writeFile, rm, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  armBootstrap,
  requireArmedBootstrap,
  consumeBootstrap,
  completeBootstrap,
  requireCompletedBootstrap,
} from "../../apps/campaign-site/src/bootstrap-control.mjs";

const actor = "11111111-1111-4111-8111-111111111111";
const other = "22222222-2222-4222-8222-222222222222";
const directory = await mkdtemp(join(tmpdir(), "cms-bootstrap-proof-"));
try {
  await assert.rejects(requireArmedBootstrap(directory, actor));
  await assert.rejects(requireCompletedBootstrap(directory));
  await armBootstrap(directory, actor);
  await requireArmedBootstrap(directory, actor);
  await assert.rejects(requireArmedBootstrap(directory, other));
  await assert.rejects(armBootstrap(directory, other));
  const attempts = await Promise.allSettled(
    Array.from({ length: 12 }, () => consumeBootstrap(directory, actor)),
  );
  assert.equal(
    attempts.filter((result) => result.status === "fulfilled").length,
    1,
  );
  await assert.rejects(requireArmedBootstrap(directory, actor));
  await assert.rejects(requireCompletedBootstrap(directory));
  await assert.rejects(completeBootstrap(directory, other));
  await completeBootstrap(directory, actor);
  await requireCompletedBootstrap(directory);
  await assert.rejects(armBootstrap(directory, actor));
  await assert.rejects(consumeBootstrap(directory, actor));
  const state = JSON.parse(
    await readFile(join(directory, "state.json"), "utf8"),
  );
  await writeFile(
    join(directory, "state.json"),
    JSON.stringify({ ...state, status: "armed", expiresAt: 0 }),
  );
  await assert.rejects(requireArmedBootstrap(directory, actor));
  await writeFile(join(directory, "state.json"), "invalid");
  await assert.rejects(requireArmedBootstrap(directory, actor));
  await rm(join(directory, "state.json"));
  await symlink("/etc/passwd", join(directory, "state.json"));
  await assert.rejects(requireArmedBootstrap(directory, actor));
  console.log(
    "emdash-bootstrap-control: OK: explicit actor-bound activation, single concurrent consumption, durable closure, expiry, corruption and symlink denial",
  );
} finally {
  await rm(directory, { recursive: true });
}
