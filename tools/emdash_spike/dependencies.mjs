import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";

const root = new URL("../../", import.meta.url);
const app = new URL("apps/campaign-site/package.json", root);
const manifest = JSON.parse(await readFile(app, "utf8"));
const publicManifest = JSON.parse(
  await readFile(new URL("apps/public/package.json", root), "utf8"),
);
for (const name of ["astro", "@astrojs/node"]) {
  assert.equal(manifest.dependencies[name], publicManifest.dependencies[name]);
}
const require = createRequire(app);
const lock = await readFile(new URL("bun.lock", root), "utf8");
const integrity =
  "sha512-dp56A8E5KCVSFVY6NSWbzgmgsUNWp7U1RX3f4qQKsY8WdB211pI3adAkLoG4R07KZ7zihxYz24DH9z5k4gLmhQ==";

assert.equal(manifest.private, true);
assert.equal(manifest.dependencies.emdash, "1.4.0");
assert.equal(manifest.dependencies.pg, "8.16.3");
assert.equal(manifest.dependencies.sharp, "0.35.5");
const sharpEntry = require.resolve("sharp");
const sharpManifest = JSON.parse(
  await readFile(new URL("../package.json", `file://${sharpEntry}`), "utf8"),
);
assert.equal(sharpManifest.version, "0.35.5");
assert.equal(sharpManifest.license, "Apache-2.0");
assert.match(lock, /"sharp@0\.35\.5"/);
assert.match(lock, /"emdash@1\.4\.0"/);
assert.ok(
  lock.includes(integrity),
  "reviewed npm integrity must remain pinned",
);
// Resolve through the workspace: EmDash deliberately does not export package.json.
const entry = require.resolve("emdash");
const installed = JSON.parse(
  await readFile(new URL("../package.json", `file://${entry}`), "utf8"),
);
assert.equal(installed.version, "1.4.0");
assert.equal(installed.license, "MIT");
assert.equal(require("pg/package.json").version, "8.16.3");

for (const name of [
  "public",
  "web",
  "pwa",
  "survey-validator",
  "campaign-site",
]) {
  const dockerfile = await readFile(
    new URL(`infra/compose/Dockerfile.${name}`, root),
    "utf8",
  );
  const stages = dockerfile
    .split(/^FROM /m)
    .filter((stage) => stage.includes("bun install --frozen-lockfile"));
  for (const stage of stages) {
    const manifests = stage.includes("COPY --from=dependencies /workspace ./")
      ? stages.find((candidate) => candidate.includes(" AS dependencies\n"))
      : stage;
    assert.ok(manifests?.includes("COPY apps/campaign-site/package.json"));
    assert.ok(manifests?.includes("COPY packages/surveys/package.json"));
  }
}
console.log(
  "emdash-dependencies: OK: exact versions, MIT license, integrity, Docker workspace parity",
);
