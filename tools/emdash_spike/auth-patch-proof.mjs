import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFile } from "node:fs/promises";
import { patchAuthSource } from "../../apps/campaign-site/emdash-auth-patch.mjs";
import { patchEditorSource } from "../../apps/campaign-site/emdash-editor-patch.mjs";

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
