import assert from "node:assert/strict";
import "./editorial-contract-proof.mjs";
import { createRequire } from "node:module";
import { readFile } from "node:fs/promises";
import { patchAuthSource } from "../../apps/campaign-site/emdash-auth-patch.mjs";
import { patchEditorSource } from "../../apps/campaign-site/emdash-editor-patch.mjs";
import {
  contentHandlerEntry,
  patchContentLogs,
} from "../../apps/campaign-site/emdash-content-log-patch.mjs";

const require = createRequire(import.meta.url);
const source = await readFile(
  require.resolve("emdash/middleware/auth"),
  "utf8",
);
const patched = patchAuthSource(source);
assert.notEqual(patched, source);
// Exercise integrity against real installed source, not a replacement module.
for (const changed of [
  source + "\n",
  source.replace("getUserByEmail", "getUserById"),
  patched,
]) {
  assert.throws(() => patchAuthSource(changed), /EmDash auth source changed/);
}
console.log(
  "emdash-auth-patch: OK: exact installed source accepted; byte drift, semantic drift and double application rejected",
);
const editor = await readFile(require.resolve("@emdash-cms/admin"), "utf8");
const revisioned = patchEditorSource(editor);
assert.notEqual(revisioned, editor);
for (const changed of [
  editor + "\n",
  editor.replace("skipRevision", "skipHistory"),
  revisioned,
]) {
  assert.throws(
    () => patchEditorSource(changed),
    /EmDash editor source changed/,
  );
}
console.log(
  "emdash-editor-patch: OK: exact published client accepted; drift and double application rejected",
);
const handlers = await readFile(contentHandlerEntry(), "utf8");
const sanitized = patchContentLogs(handlers);
assert.notEqual(sanitized, handlers);
assert.equal([...sanitized.matchAll(/console\.error\(/g)].length, 21);
assert.equal(
  [...sanitized.matchAll(/console\.error\("[^"\n]+"\);/g)].length,
  21,
);
for (const changed of [
  handlers + "\n",
  handlers.replace("Content create error", "Changed create error"),
  sanitized,
]) {
  assert.throws(
    () => patchContentLogs(changed),
    /EmDash content source changed/,
  );
}
console.log(
  "emdash-content-log-patch: OK: all 21 fixed signals retained without exception objects or item identifiers; source drift and double application denied",
);
