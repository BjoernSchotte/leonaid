import assert from "node:assert/strict";
import ts from "typescript";
import { campaignCollection } from "../../apps/campaign-site/src/campaign-schema.mjs";
import { generateCampaignTypes } from "./campaign-typegen.mjs";

const expected = await generateCampaignTypes();
assert.equal(expected, await generateCampaignTypes());
assert.equal(
  expected,
  await generateCampaignTypes({
    ...campaignCollection,
    fields: [...campaignCollection.fields].reverse(),
  }),
);
for (const field of [
  { slug: "unsupported", type: "json" },
  { slug: "unsafe-name;", type: "text" },
  { slug: "empty_select", type: "select", validation: { options: [] } },
  { slug: "empty_repeater", type: "repeater" },
  campaignCollection.fields[0],
]) {
  await assert.rejects(
    generateCampaignTypes({
      ...campaignCollection,
      fields: [...campaignCollection.fields, field],
    }),
    /campaign_typegen_/,
  );
}
assert.notEqual(
  expected,
  await generateCampaignTypes({
    ...campaignCollection,
    fields: campaignCollection.fields.map((field) =>
      field.slug === "theme"
        ? { ...field, validation: { options: ["new-reviewed-theme"] } }
        : field,
    ),
  }),
);

// Compile real checked-in source, including negative assignments checked by
// @ts-expect-error. No emission, network, development server or database needed.
const program = ts.createProgram(
  ["tools/emdash_spike/campaign-types-fixture.ts"],
  {
    noEmit: true,
    strict: true,
    skipLibCheck: true,
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.NodeNext,
    moduleResolution: ts.ModuleResolutionKind.NodeNext,
  },
);
const diagnostics = ts.getPreEmitDiagnostics(program);
assert.equal(
  diagnostics.length,
  0,
  ts.formatDiagnostics(diagnostics, {
    getCanonicalFileName: (file) => file,
    getCurrentDirectory: () => process.cwd(),
    getNewLine: () => "\n",
  }),
);
console.log(
  "campaign-typegen: OK: deterministic types, schema-change detection, unsupported-field denial, positive/negative TypeScript compilation",
);
