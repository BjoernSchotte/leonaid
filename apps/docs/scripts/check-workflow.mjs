import { readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { load as loadYaml } from "js-yaml";

const repositoryRoot = path.resolve(import.meta.dirname, "../../..");
const workflowPath = path.join(repositoryRoot, ".github/workflows/docs.yml");
const workflow = loadYaml(await readFile(workflowPath, "utf8"));
const errors = [];
const events = workflow.on ?? {};

for (const event of ["pull_request", "push", "schedule", "workflow_dispatch"]) {
  if (!(event in events)) errors.push(`missing workflow event ${event}`);
}
if (events.push?.branches?.join(",") !== "main") {
  errors.push("push event must target main");
}
if (events.schedule?.[0]?.cron !== "23 2 * * *") {
  errors.push("nightly schedule must be 02:23 UTC");
}
if (workflow.permissions?.contents !== "read") {
  errors.push("workflow permissions must keep repository contents read-only");
}

const jobs = Object.values(workflow.jobs ?? {});
if (jobs.length !== 1)
  errors.push("docs workflow must use one shared gate job");
const steps = jobs[0]?.steps ?? [];
const commands = steps
  .map((step) => step.run)
  .filter((run) => typeof run === "string")
  .join("\n");
for (const command of [
  "./leonaid bootstrap",
  "./leonaid docs-check",
  "./leonaid docs-build",
  "./leonaid test-docs",
]) {
  if (!commands.includes(command))
    errors.push(`missing shared gate ${command}`);
}

const actions = steps
  .map((step) => step.uses)
  .filter((uses) => typeof uses === "string");
for (const action of actions) {
  if (!/@[0-9a-f]{40}$/.test(action))
    errors.push(`action is not SHA-pinned: ${action}`);
}
const siteUpload = steps.find(
  (step) => step.name === "Publish complete documentation site",
);
if (siteUpload?.with?.path !== "apps/docs/dist") {
  errors.push("site artifact must contain only apps/docs/dist");
}
if (steps.some((step) => /deploy/i.test(step.name ?? ""))) {
  errors.push("DOC-060 workflow must not deploy before DOC-070");
}

if (errors.length) {
  console.error(`docs-workflow: FAILED (${errors.length})`);
  for (const error of errors) console.error(`- ${error}`);
  process.exitCode = 1;
} else {
  console.log(
    "docs-workflow: OK: PR, main push, 02:23 UTC schedule and manual runs share pinned read-only gates",
  );
}
