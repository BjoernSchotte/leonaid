import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";

const root = new URL("../../", import.meta.url);
const app = new URL("apps/campaign-site/package.json", root);
const manifest = JSON.parse(await readFile(app, "utf8"));
const require = createRequire(app);
const lock = await readFile(new URL("bun.lock", root), "utf8");
const integrity =
  "sha512-a/lldbDMig8z3WycPliHwZ2VwFQl9ewT9OMvK9/2gvbzoJOXXUF73KTK7AThSss5SbT1oj0h9exGa/GyIr3vAw==";

assert.equal(manifest.private, true);
assert.equal(manifest.dependencies.emdash, "0.36.0");
assert.equal(manifest.dependencies.pg, "8.16.3");
assert.match(lock, /"emdash@0\.36\.0"/);
assert.ok(
  lock.includes(integrity),
  "reviewed npm integrity must remain pinned",
);
// Resolve through the workspace: EmDash deliberately does not export package.json.
const entry = require.resolve("emdash");
const installed = JSON.parse(
  await readFile(new URL("../package.json", `file://${entry}`), "utf8"),
);
assert.equal(installed.version, "0.36.0");
assert.equal(installed.license, "MIT");
assert.equal(require("pg/package.json").version, "8.16.3");

for (const name of ["public", "web", "pwa"]) {
  const dockerfile = await readFile(
    new URL(`infra/compose/Dockerfile.${name}`, root),
    "utf8",
  );
  const stages = dockerfile
    .split(/^FROM /m)
    .filter((stage) => stage.includes("bun install --frozen-lockfile"));
  for (const stage of stages) {
    assert.ok(stage.includes("COPY apps/campaign-site/package.json"));
  }
}
console.log(
  "emdash-dependencies: OK: exact versions, MIT license, integrity, Docker workspace parity",
);
