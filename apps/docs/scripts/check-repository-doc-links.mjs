import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const projectRoot = path.resolve(import.meta.dirname, "../../..");
const contracts = {
  "README.md": [
    "apps/docs/src/content/docs/de/index.mdx",
    "apps/docs/src/content/docs/en/index.mdx",
    "apps/docs/src/content/docs/de/user/index.mdx",
    "apps/docs/src/content/docs/en/user/index.mdx",
    "apps/docs/src/content/docs/de/ops/index.mdx",
    "apps/docs/src/content/docs/en/ops/index.mdx",
    "apps/docs/src/content/docs/de/dev/index.mdx",
    "apps/docs/src/content/docs/en/dev/index.mdx",
    "apps/docs/src/content/docs/de/known-limits.md",
    "apps/docs/src/content/docs/en/known-limits.md",
  ],
  "infra/compose/README.md": [
    "../../apps/docs/src/content/docs/de/ops/tutorials/local-demo.md",
    "../../apps/docs/src/content/docs/en/ops/tutorials/local-demo.md",
  ],
  "infra/pilot/README.md": [
    "../../apps/docs/src/content/docs/de/ops/how-to/deploy-pilot.md",
    "../../apps/docs/src/content/docs/en/ops/how-to/deploy-pilot.md",
  ],
  "infra/backup/README.md": [
    "../../apps/docs/src/content/docs/de/ops/how-to/backup-and-restore.md",
    "../../apps/docs/src/content/docs/en/ops/how-to/backup-and-restore.md",
  ],
  "infra/upgrade/README.md": [
    "../../apps/docs/src/content/docs/de/ops/how-to/upgrade-and-rollback.md",
    "../../apps/docs/src/content/docs/en/ops/how-to/upgrade-and-rollback.md",
  ],
  "migrations/README.md": [
    "../apps/docs/src/content/docs/de/dev/how-to/add-migration.md",
    "../apps/docs/src/content/docs/en/dev/how-to/add-migration.md",
  ],
  "specs/leonaid-poc/DEVELOPMENT.md": [
    "../../apps/docs/src/content/docs/de/dev/index.mdx",
    "../../apps/docs/src/content/docs/en/dev/index.mdx",
  ],
  "specs/leonaid-poc/ARCHITECTURE.md": [
    "../../apps/docs/src/content/docs/de/dev/explanation/architecture-and-data-ownership.md",
    "../../apps/docs/src/content/docs/en/dev/explanation/architecture-and-data-ownership.md",
  ],
};
const errors = [];

for (const [source, targets] of Object.entries(contracts)) {
  const sourcePath = path.join(projectRoot, source);
  const text = await readFile(sourcePath, "utf8");
  for (const target of targets) {
    if (!text.includes(`](${target})`)) {
      errors.push(`${source}: missing canonical link ${target}`);
      continue;
    }
    const targetPath = path.resolve(path.dirname(sourcePath), target);
    try {
      if (!(await stat(targetPath)).isFile()) {
        errors.push(`${source}: target is not a file ${target}`);
      }
    } catch (error) {
      if (error.code === "ENOENT")
        errors.push(`${source}: target missing ${target}`);
      else throw error;
    }
  }
}

const rootReadme = await readFile(path.join(projectRoot, "README.md"), "utf8");
if (
  !rootReadme.startsWith("# LeonAid\n") ||
  !rootReadme.includes("## Documentation")
) {
  errors.push("README.md: English GitHub entry headings are missing");
}
if (rootReadme.split("\n").length > 45) {
  errors.push("README.md: compact GitHub entry exceeds 45 lines");
}

if (errors.length) {
  console.error(`docs-repository-links: FAILED (${errors.length})`);
  for (const error of errors) console.error(`- ${error}`);
  process.exitCode = 1;
} else {
  console.log(
    `docs-repository-links: OK: ${Object.keys(contracts).length} entry points link to existing bilingual sources`,
  );
}
