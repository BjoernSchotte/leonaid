import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { generateCampaignTypes } from "./campaign-typegen.mjs";

assert.ok(
  process.argv.length === 2 ||
    (process.argv.length === 3 && process.argv[2] === "--check"),
  "usage: export-types.mjs [--check]",
);
const generated = await generateCampaignTypes();
if (process.argv[2] === "--check") {
  assert.equal(
    await readFile(
      new URL(
        "../../apps/campaign-site/src/campaign-fields.generated.ts",
        import.meta.url,
      ),
      "utf8",
    ),
    generated,
    "campaign types are stale; regenerate and review the schema change",
  );
  console.log("campaign-typegen: OK: committed types match source schema");
} else {
  process.stdout.write(generated);
}
