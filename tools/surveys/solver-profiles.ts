/**
 * SurveyJS results per answer profile for the disclosure solver
 * (tests/unit/survey_solver_scenarios.py).
 *
 *   bun tools/surveys/solver-profiles.ts write <scenarios.json> <profiles.json>
 *   bun tools/surveys/solver-profiles.ts check <profiles.json>
 *
 * For each profile: the counts aggregateApprovedSurvey records for one
 * person, the answers left after hidden-value clearing, and the last
 * visible page (where a completed participation is saved). This is the
 * runner's survey-core, so visibility, empty pages and the comparator
 * (case, trimming, number conversion) are SurveyJS's own.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { aggregateApprovedSurvey } from "../../packages/surveys/src/analysis";
import {
  createSurveyModel,
  restoreSurveyAnswers,
} from "../../packages/surveys/src/model";

type Scenario = {
  definition: Record<string, unknown>;
  profiles: Record<string, unknown>[];
};

function evaluate(scenarios: Record<string, Scenario>) {
  const results: Record<string, unknown[]> = {};
  for (const name of Object.keys(scenarios).sort()) {
    const { definition, profiles } = scenarios[name];
    results[name] = profiles.map((answers) => {
      const model = createSurveyModel(definition);
      restoreSurveyAnswers(model, answers);
      const pages = model.visiblePages;
      return {
        questions: aggregateApprovedSurvey(definition, [answers]),
        values: model.data,
        lastPage: pages.length ? pages[pages.length - 1].name : null,
      };
    });
  }
  return results;
}

const [mode, first, second] = process.argv.slice(2);
if (mode === "write" && first && second) {
  const scenarios = JSON.parse(readFileSync(first, "utf8"));
  writeFileSync(
    second,
    JSON.stringify({ scenarios, results: evaluate(scenarios) }, null, 1) + "\n",
  );
} else if (mode === "check" && first) {
  const fixture = JSON.parse(readFileSync(first, "utf8"));
  const fresh = JSON.stringify(evaluate(fixture.scenarios));
  if (fresh !== JSON.stringify(fixture.results)) {
    console.error("solver-profiles: FAILED: results differ from SurveyJS");
    process.exit(1);
  }
  console.log("solver-profiles: OK: stored results match SurveyJS");
} else {
  console.error("usage: solver-profiles.ts write <in> <out> | check <fixture>");
  process.exit(2);
}
