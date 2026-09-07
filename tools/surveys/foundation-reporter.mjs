import { writeFileSync } from "node:fs";
import { relative } from "node:path";

const phases = new Set(["member-host", "public-host", "public-survey-shell"]);
const statuses = new Set([
  "passed",
  "failed",
  "timedOut",
  "skipped",
  "interrupted",
]);
const file = "tests/e2e/surveys-infrastructure.spec.mjs";
const location = (value) => ({
  file:
    value?.file && relative(process.cwd(), value.file) === file
      ? file
      : "external",
  line: Number.isInteger(value?.line) ? value.line : 0,
  column: Number.isInteger(value?.column) ? value.column : 0,
});

// Deliberately omit titles, messages, snippets, stacks, attachments and stdout:
// all can contain cookies, response text or URLs with resume credentials.
export default class FoundationReporter {
  cases = [];
  completed = new Set();
  globalErrors = 0;

  printsToStdio() {
    return true;
  }
  onStdOut() {}
  onStdErr() {}
  onError() {
    this.globalErrors += 1;
  }
  onStepEnd(_test, _result, step) {
    if (phases.has(step.title) && !step.error) this.completed.add(step.title);
  }
  onTestEnd(test, result) {
    this.cases.push({
      location: location(test.location),
      status: statuses.has(result.status) ? result.status : "unknown",
      errors: result.errors.map((error) => ({
        category:
          result.status === "timedOut"
            ? "timeout"
            : /expect\(|AssertionError/.test(error.message ?? "")
              ? "assertion"
              : "error",
        location: location(error.location ?? test.location),
      })),
    });
  }
  onEnd(result) {
    const report = {
      schemaVersion: 1,
      status: statuses.has(result.status) ? result.status : "unknown",
      completedPhases: [...this.completed],
      globalErrors: this.globalErrors,
      cases: this.cases,
    };
    writeFileSync(
      `${process.env.LEONAID_E2E_ARTIFACT_DIR}/foundation-diagnostics.json`,
      JSON.stringify(report, null, 2) + "\n",
    );
    console.log(
      `Survey foundation: ${report.status}; ${report.completedPhases.join(", ")}`,
    );
    for (const entry of report.cases)
      for (const error of entry.errors)
        console.log(
          `${error.category}: ${error.location.file}:${error.location.line}`,
        );
  }
}
