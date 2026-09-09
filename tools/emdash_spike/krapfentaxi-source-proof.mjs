import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  mkdtemp,
  mkdir,
  copyFile,
  readFile,
  writeFile,
  symlink,
  unlink,
  rm,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import {
  loadKrapfentaxiSource,
  krapfentaxiImportData,
} from "./krapfentaxi-source.mjs";
import { normalizeCampaignImage } from "../../apps/campaign-site/src/auth/campaign-image.mjs";

const root = new URL("../../", import.meta.url);
const source = await loadKrapfentaxiSource();
assert.deepEqual(await loadKrapfentaxiSource(), source);
assert.equal(source.assets.length, 3);
assert.equal(source.manifest.version, 1);
assert.equal(source.manifest.productionRightsCleared, false);
assert.match(source.manifest.rightsNotice, /Rechte verbleiben/);
assert.match(source.manifest.rightsNotice, /vor einem produktiven/);
assert.equal(
  source.fingerprint,
  createHash("sha256").update(JSON.stringify(source.manifest)).digest("hex"),
);
const actionId = "20000000-0000-4000-8000-000000000001";
const media = {};
for (const [index, asset] of source.assets.entries()) {
  const image = await normalizeCampaignImage(asset.bytes, asset.mimeType);
  media[asset.key] = {
    id: `01ARZ3NDEKTSV4RRFFQ69G5FA${index}`,
    status: "ready",
    actionId,
    width: image.width,
    height: image.height,
  };
  assert.equal(
    asset.sha256,
    createHash("sha256").update(asset.bytes).digest("hex"),
  );
  assert.equal(source.manifest.assets[index].size, asset.bytes.length);
  assert.equal(source.manifest.assets[index].source, asset.source);
}
const data = krapfentaxiImportData(actionId, media);
const legacyText = (
  await readFile(new URL(source.manifest.sources[0].path, root), "utf8")
)
  .replace(/<[^>]*>/g, " ")
  .replace(/\s+/g, " ");
for (const text of [
  data.hero_summary,
  data.story_eyebrow,
  data.story_title,
  ...data.body.map((block) => block.children[0].text),
  data.partners[0].name,
  data.partners[0].eyebrow,
  data.partners[0].description,
  data.partners[0].link_label,
])
  assert.ok(
    legacyText.includes(text.replace(/\s+/g, " ")),
    "import copy must match the pinned original component",
  );
assert.equal(data.action_id, actionId);
assert.equal(data.hero_image.id, data.social_image.id);
assert.equal(data.brand_logo.id, media.logo.id);
assert.equal(data.partners[0].logo.id, media.partner.id);
assert.equal(data.hero_title, null);
assert.deepEqual(data.hero_summary, source.manifest.editorial.hero_summary);
for (const key of [
  "name",
  "purpose",
  "startsOn",
  "endsOn",
  "offerings",
  "price",
  "beneficiaries",
  "orderForm",
  "action_id",
])
  assert.equal(Object.hasOwn(source.manifest.editorial, key), false);
assert.ok(!JSON.stringify(data).includes("storageKey"));
assert.ok(!JSON.stringify(data).includes("productionRightsCleared"));
const changed = krapfentaxiImportData(actionId, media);
changed.body[0].children[0].text = "Changed locally";
assert.deepEqual(krapfentaxiImportData(actionId, media), data);
for (const invalid of ["", "krapfentaxi", actionId + "/"])
  assert.throws(
    () => krapfentaxiImportData(invalid, media),
    /krapfentaxi_action_invalid/,
  );
for (const overrides of [
  { status: "pending" },
  { actionId: "20000000-0000-4000-8000-000000000002" },
  { width: 0 },
  { height: 8193 },
  { id: "unscoped" },
])
  assert.throws(
    () =>
      krapfentaxiImportData(actionId, {
        ...media,
        logo: { ...media.logo, ...overrides },
      }),
    /krapfentaxi_media_invalid/,
  );

// Real filesystem drift checks on a throwaway source tree. The checkout is
// mounted read-only by the runner, and no network/DB/storage credentials exist.
const fixture = await mkdtemp(join(tmpdir(), "leonaid-source-proof-"));
try {
  const files = [...source.manifest.sources, ...source.manifest.assets].map(
    (item) => item.path,
  );
  for (const path of [
    ...files,
    "tools/emdash_spike/krapfentaxi-source.mjs",
    "apps/campaign-site/src/auth/campaign-editorial.mjs",
  ]) {
    const target = join(fixture, path);
    await mkdir(join(target, ".."), { recursive: true });
    await copyFile(new URL(path, root), target);
  }
  await symlink(
    fileURLToPath(new URL("node_modules", root)),
    join(fixture, "node_modules"),
  );
  const isolated = await import(
    pathToFileURL(join(fixture, "tools/emdash_spike/krapfentaxi-source.mjs"))
      .href
  );
  assert.deepEqual(await isolated.loadKrapfentaxiSource(), source);
  for (const path of files) {
    const target = join(fixture, path);
    const original = await readFile(target);
    await writeFile(
      target,
      Buffer.concat([original, Buffer.from("source drift")]),
    );
    await assert.rejects(
      isolated.loadKrapfentaxiSource(),
      /krapfentaxi_source_drift/,
    );
    await writeFile(target, original);
  }
  const image = join(fixture, source.assets[0].path);
  await unlink(image);
  await symlink(fileURLToPath(new URL(source.assets[0].path, root)), image);
  await assert.rejects(
    isolated.loadKrapfentaxiSource(),
    (error) => error.code === "ELOOP",
  );
} finally {
  await rm(fixture, { recursive: true, force: true });
}
console.log(
  "krapfentaxi-source: OK: actual three raster assets decode, deterministic content/provenance fingerprint, preserved rights notice, no Core business snapshots, scoped payload checks and actual five-file/symlink drift denial; import writes remain a separate gate",
);
