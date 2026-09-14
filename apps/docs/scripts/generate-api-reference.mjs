import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const projectRoot = path.resolve(import.meta.dirname, "../../..");
const sourcePath = path.join(projectRoot, "packages/api-client/openapi.json");
const targetPath = path.join(
  projectRoot,
  "apps/docs/src/generated/openapi-reference.json",
);
const methods = ["get", "post", "put", "patch", "delete"];
const source = await readFile(sourcePath);
const contract = JSON.parse(source.toString("utf8"));
const grouped = new Map();

for (const route of Object.keys(contract.paths ?? {}).sort()) {
  const pathItem = contract.paths[route];
  for (const method of methods) {
    const operation = pathItem[method];
    if (!operation) continue;
    const tag = operation.tags?.[0] ?? "other";
    const entries = grouped.get(tag) ?? [];
    entries.push({
      method: method.toUpperCase(),
      operationId: operation.operationId ?? "—",
      path: route,
      responses: Object.keys(operation.responses ?? {}).sort(),
      summary: operation.summary ?? operation.operationId ?? route,
    });
    grouped.set(tag, entries);
  }
}

const output = {
  contract: {
    openapi: contract.openapi,
    sha256: createHash("sha256").update(source).digest("hex"),
    title: contract.info?.title,
    version: contract.info?.version,
  },
  schemaCount: Object.keys(contract.components?.schemas ?? {}).length,
  tags: [...grouped.entries()]
    .sort(([left], [right]) => left.localeCompare(right, "en"))
    .map(([name, operations]) => ({ name, operations })),
};

await mkdir(path.dirname(targetPath), { recursive: true });
await writeFile(targetPath, `${JSON.stringify(output, null, 2)}\n`, "utf8");
console.log(
  `docs-api-reference: OK: ${output.tags.length} tags, ${output.tags.reduce((sum, tag) => sum + tag.operations.length, 0)} operations, sha256=${output.contract.sha256}`,
);
