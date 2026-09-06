import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import assert from "node:assert/strict";
const require = createRequire(import.meta.url);
const allowed = new Map([
  ["survey-core", ["3.0.3", "MIT"]],
  ["survey-react-ui", ["3.0.3", "MIT"]],
  ["react", ["19.2.8", "MIT"]],
  ["react-dom", ["19.2.8", "MIT"]],
  ["scheduler", ["0.27.0", "MIT"]],
]);
export function checkManifest(manifest) {
  const expected = allowed.get(manifest.name);
  assert.ok(expected, `Unreviewed dependency: ${manifest.name}`);
  assert.equal(
    manifest.version,
    expected[0],
    `Unreviewed version: ${manifest.name}`,
  );
  assert.equal(
    manifest.license,
    expected[1],
    `Unreviewed license: ${manifest.name}`,
  );
  for (const name of Object.keys({
    ...manifest.dependencies,
    ...manifest.peerDependencies,
  })) {
    assert.ok(allowed.has(name), `Unreviewed transitive dependency: ${name}`);
  }
}
const root = JSON.parse(
  readFileSync(new URL("../../packages/surveys/package.json", import.meta.url)),
);
for (const name of Object.keys({
  ...root.dependencies,
  ...root.peerDependencies,
  ...root.devDependencies,
})) {
  assert.ok(allowed.has(name), `Unreviewed package dependency: ${name}`);
}
const inventory = [];
for (const name of allowed.keys()) {
  const manifest = JSON.parse(
    readFileSync(require.resolve(`${name}/package.json`)),
  );
  checkManifest(manifest);
  inventory.push({
    name,
    version: manifest.version,
    license: manifest.license,
  });
}
const fontLicense = readFileSync(
  new URL("../../node_modules/survey-core/fonts/LICENSE.txt", import.meta.url),
  "utf8",
);
assert.match(fontLicense, /SIL OPEN FONT LICENSE Version 1.1/);
for (const bad of [
  { name: "survey-creator-core", version: "3.0.3", license: "MIT" },
  { name: "survey-core", version: "3.0.3", license: "Commercial" },
  { name: "survey-core", version: "3.0.4", license: "MIT" },
  {
    name: "survey-core",
    version: "3.0.3",
    license: "MIT",
    dependencies: { unknown: "1" },
  },
])
  assert.throws(() => checkManifest(bad));
console.log(
  JSON.stringify(
    {
      software: inventory,
      assets: [{ name: "Open Sans", license: "OFL-1.1" }],
      negativeCases: 4,
    },
    null,
    2,
  ),
);
