// Unit tests of the CMS provisioning state classification and the SCRAM
// verifier (./leonaid check: node --test tools/pilot_cms/).
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  databaseErrorState,
  migrationState,
  schemaState,
  storageErrorState,
} from "../../apps/campaign-site/src/cms-provision-state.mjs";
import { scramSha256Verifier } from "../../apps/campaign-site/src/provision-postgres.mjs";

test("database: authentication and unknown database mean the step is open", () => {
  for (const code of ["28P01", "28000", "3D000"])
    assert.equal(databaseErrorState({ code }), "missing");
  // Server down, timeout, refused connection: an outage, never a step to run.
  for (const error of [
    { code: "ECONNREFUSED" },
    { code: "57P03" },
    new Error("timeout exceeded when trying to connect"),
    undefined,
  ])
    assert.equal(databaseErrorState(error), "unavailable");
});

test("storage: an S3 client error means open, no answer means outage", () => {
  for (const status of [403, 404])
    assert.equal(
      storageErrorState({ cause: { $metadata: { httpStatusCode: status } } }),
      "missing",
    );
  assert.equal(
    storageErrorState({ $metadata: { httpStatusCode: 404 } }),
    "missing",
  );
  for (const error of [
    { cause: { $metadata: { httpStatusCode: 503 } } },
    { cause: { code: "ECONNREFUSED" } },
    { cause: { $metadata: {} } },
    undefined,
  ])
    assert.equal(storageErrorState(error), "unavailable");
});

test("migrations: exact list ready, gapless prefix open, anything else refused", () => {
  const names = ["001", "002", "003"];
  const status = (knownApplied, unknownApplied = []) => ({
    knownApplied,
    unknownApplied,
    pending: names.filter((name) => !knownApplied.includes(name)),
  });
  assert.equal(migrationState(status(names), names), "ready");
  assert.equal(migrationState(status([]), names), "missing");
  assert.equal(migrationState(status(["001", "002"]), names), "missing");
  assert.equal(migrationState(status(["001", "003"]), names), "refused");
  assert.equal(migrationState(status(names, ["999"]), names), "refused");
  assert.equal(migrationState(status([], ["999"]), names), "refused");
});

test("schema: missing, partial after an interrupted install, ready, refused", () => {
  const expected = { schema: "3", bindings: "2", media: "1" };
  const ok = { schema: true, bindings: true, media: true };
  assert.equal(schemaState({}, expected, {}), "missing");
  // Interrupted between the installers: the later parts are absent.
  assert.equal(
    schemaState({ schema: "3" }, expected, { schema: true }),
    "partial",
  );
  assert.equal(
    schemaState({ schema: "3", bindings: "2" }, expected, {
      schema: true,
      bindings: true,
    }),
    "partial",
  );
  assert.equal(schemaState(expected, expected, ok), "ready");
  // Another release's schema, a drifted guard, guards without a schema.
  assert.equal(
    schemaState({ ...expected, schema: "2" }, expected, ok),
    "refused",
  );
  assert.equal(
    schemaState(expected, expected, { ...ok, bindings: false }),
    "refused",
  );
  assert.equal(
    schemaState({ schema: "3", media: "1" }, expected, {
      schema: true,
      media: false,
    }),
    "refused",
  );
  assert.equal(
    schemaState({ bindings: "2" }, expected, { bindings: true }),
    "refused",
  );
});

test("SCRAM verifier: PostgreSQL format, salted, no plaintext", () => {
  const password = "cms-password-0123456789-abcdefghijkl";
  const salt = Buffer.alloc(16, 7);
  const verifier = scramSha256Verifier(password, salt);
  assert.match(
    verifier,
    /^SCRAM-SHA-256\$4096:[A-Za-z0-9+/]+=*\$[A-Za-z0-9+/]+=*:[A-Za-z0-9+/]+=*$/,
  );
  assert.equal(verifier.includes(password), false);
  assert.equal(scramSha256Verifier(password, salt), verifier);
  assert.notEqual(scramSha256Verifier(password), verifier);
  assert.throws(() => scramSha256Verifier("with space"));
});
