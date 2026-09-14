import { readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const projectRoot = path.resolve(import.meta.dirname, "../../..");
const contractPath = path.join(projectRoot, "apps/docs/product-contracts.json");
const contracts = JSON.parse(await readFile(contractPath, "utf8"));
const errors = [];

for (const [docId, sources] of Object.entries(contracts)) {
  for (const source of sources) {
    const file = path.join(projectRoot, source.file);
    const text = await readFile(file, "utf8");
    for (const expected of source.contains) {
      if (!text.includes(expected)) {
        errors.push(
          `${docId}: ${source.file} no longer contains ${JSON.stringify(expected)}`,
        );
      }
    }
  }
}

if (errors.length) {
  console.error(`docs-product-contracts: FAILED (${errors.length})`);
  for (const error of errors) console.error(`- ${error}`);
  process.exitCode = 1;
} else {
  console.log(
    `docs-product-contracts: OK: ${Object.keys(contracts).length} user and technical pages match current code and contract tokens`,
  );
}
