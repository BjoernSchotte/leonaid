import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";

// Exercise the actual pinned upstream CLI with synthetic key material only.
// No custom encryption substitute: this upstream version has no plugin-secret
// encrypt/decrypt layer. The backup contract must agree with its key parser.
const cli = new URL(
  "../../node_modules/emdash/dist/cli/index.mjs",
  import.meta.url,
);
for (const [body, valid] of [
  ["A".repeat(43), true],
  ["B".repeat(42) + "A", true],
  ["A".repeat(42) + "B", false],
  ["A".repeat(42) + "_", false],
]) {
  const result = spawnSync(
    process.execPath,
    [cli.pathname, "secrets", "fingerprint", `emdash_enc_v1_${body}`],
    { encoding: "utf8", timeout: 30000 },
  );
  assert.equal(result.error, undefined);
  if (valid) {
    assert.equal(result.status, 0);
    const expected = createHash("sha256")
      .update(Buffer.from(body, "base64url"))
      .digest("hex")
      .slice(0, 8);
    assert.ok(result.stdout.includes(expected));
  } else assert.notEqual(result.status, 0);
}
console.log(
  "recovery-key: actual pinned EmDash CLI accepts canonical keys and rejects non-canonical padding bits; no encryption claim",
);
