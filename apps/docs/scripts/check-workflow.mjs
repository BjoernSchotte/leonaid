import { readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { load as loadYaml } from "js-yaml";

const repositoryRoot = path.resolve(import.meta.dirname, "../../..");
const workflowPath = path.join(repositoryRoot, ".github/workflows/docs.yml");
const workflow = loadYaml(await readFile(workflowPath, "utf8"));
const watchdogPath = path.join(
  repositoryRoot,
  ".github/workflows/docs-watchdog.yml",
);
const watchdog = loadYaml(await readFile(watchdogPath, "utf8"));
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
if (
  workflow.concurrency?.group !== "documentation-${{ github.ref }}" ||
  workflow.concurrency?.["cancel-in-progress"] !== true
) {
  errors.push("workflow must cancel stale runs for the same ref");
}

const build = workflow.jobs?.build;
const deploy = workflow.jobs?.deploy;
if (Object.keys(workflow.jobs ?? {}).join(",") !== "build,deploy") {
  errors.push("docs workflow must contain only build and deploy jobs");
}
const buildSteps = build?.steps ?? [];
const buildCommands = buildSteps
  .map((step) => step.run)
  .filter((run) => typeof run === "string")
  .join("\n");
for (const command of [
  "./leonaid bootstrap",
  "./leonaid docs-check",
  "./leonaid docs-build",
  "./leonaid test-docs",
]) {
  if (!buildCommands.includes(command))
    errors.push(`missing shared gate ${command}`);
}
if (build?.env?.LEONAID_DOCS_SITE_URL !== "https://bjoernschotte.github.io") {
  errors.push("build must use the GitHub Pages site origin");
}
if (build?.env?.LEONAID_DOCS_BASE_PATH !== "/leonaid") {
  errors.push("build must use the /leonaid Pages base path");
}

const actions = [...buildSteps, ...(deploy?.steps ?? [])]
  .map((step) => step.uses)
  .filter((uses) => typeof uses === "string");
for (const action of actions) {
  if (!/@[0-9a-f]{40}$/.test(action))
    errors.push(`action is not SHA-pinned: ${action}`);
}
const siteUpload = buildSteps.find(
  (step) => step.name === "Publish complete documentation site",
);
if (siteUpload?.with?.path !== "apps/docs/dist") {
  errors.push("site artifact must contain only apps/docs/dist");
}
const pagesUpload = buildSteps.find(
  (step) => step.name === "Stage GitHub Pages artifact",
);
if (pagesUpload?.with?.path !== "apps/docs/dist") {
  errors.push("Pages artifact must contain only apps/docs/dist");
}
if (!pagesUpload?.uses?.startsWith("actions/upload-pages-artifact@")) {
  errors.push("Pages artifact must use actions/upload-pages-artifact");
}
if (!String(pagesUpload?.if).includes("refs/heads/main")) {
  errors.push("Pages artifact must be limited to the default branch");
}
for (const event of ["schedule", "workflow_dispatch"]) {
  if (!String(pagesUpload?.if).includes(`github.event_name == '${event}'`)) {
    errors.push(`Pages artifact must be limited to ${event} publications`);
  }
}
if (deploy?.needs !== "build") {
  errors.push("deployment must depend on the shared build job");
}
if (!String(deploy?.if).includes("refs/heads/main")) {
  errors.push("deployment must be limited to the default branch");
}
for (const event of ["schedule", "workflow_dispatch"]) {
  if (!String(deploy?.if).includes(`github.event_name == '${event}'`)) {
    errors.push(`deployment must be limited to ${event} publications`);
  }
}
if (deploy?.environment?.name !== "github-pages") {
  errors.push("deployment must use the github-pages environment");
}
if (
  JSON.stringify(deploy?.permissions) !==
  JSON.stringify({
    actions: "read",
    contents: "read",
    "id-token": "write",
    pages: "write",
  })
) {
  errors.push("deployment permissions must be minimal for GitHub Pages");
}
if (
  deploy?.concurrency?.group !== "github-pages" ||
  deploy?.concurrency?.["cancel-in-progress"] !== true
) {
  errors.push("Pages deployments must cancel stale in-progress revisions");
}
const deploySteps = deploy?.steps ?? [];
if (
  !deploySteps.some((step) => step.uses?.startsWith("actions/deploy-pages@"))
) {
  errors.push("deployment must use actions/deploy-pages");
}
const deployCommands = deploySteps
  .map((step) => step.run)
  .filter((run) => typeof run === "string")
  .join("\n");
for (const command of ["./leonaid bootstrap", "./leonaid test-docs"]) {
  if (!deployCommands.includes(command)) {
    errors.push(`missing live deployment gate ${command}`);
  }
}
const liveSmoke = deploySteps.find(
  (step) => step.name === "Smoke deployed revision",
);
if (liveSmoke?.env?.LEONAID_DOCS_EXPECTED_REVISION !== "${{ github.sha }}") {
  errors.push("live smoke must verify the deployed source revision");
}

const watchdogEvents = watchdog.on ?? {};
if (
  watchdogEvents.workflow_run?.workflows?.join(",") !== "Documentation" ||
  watchdogEvents.workflow_run?.types?.join(",") !== "completed"
) {
  errors.push("watchdog must observe completed Documentation workflows");
}
if (watchdogEvents.schedule?.[0]?.cron !== "47 */6 * * *") {
  errors.push("watchdog must check independently every six hours");
}
if (
  JSON.stringify(watchdog.permissions) !==
  JSON.stringify({ actions: "read", issues: "write" })
) {
  errors.push("watchdog permissions must be limited to actions and issues");
}
const watchdogJob = watchdog.jobs?.monitor;
const watchdogScript = watchdogJob?.steps?.[0]?.run ?? "";
for (const contract of [
  "github.event.workflow_run.head_branch == 'main'",
  'RUN_EVENT" != schedule',
  'RUN_EVENT" != workflow_dispatch',
  '.event == "schedule" or .event == "workflow_dispatch"',
  "-gt 108000",
  "gh issue create",
  "gh issue close",
]) {
  if (!`${watchdogJob?.if ?? ""}\n${watchdogScript}`.includes(contract)) {
    errors.push(`watchdog is missing ${contract}`);
  }
}

if (errors.length) {
  console.error(`docs-workflow: FAILED (${errors.length})`);
  for (const error of errors) console.error(`- ${error}`);
  process.exitCode = 1;
} else {
  console.log(
    "docs-workflow: OK: shared gates, main-only Pages deployment, live smoke and independent publication watchdog",
  );
}
