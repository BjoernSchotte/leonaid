// Isolated feasibility process: input contains only host-approved synthetic
// definitions. This is deliberately not a network service or production adapter.
import { evaluateApprovedSurvey } from "../../packages/surveys/src/validation-candidate.ts";
import { readFileSync, writeFileSync } from "node:fs";

const requests = JSON.parse(readFileSync(process.argv[2], "utf8"));
const results = requests.map(({ name, definition, answers }) => ({
  name,
  ...evaluateApprovedSurvey(definition, answers),
}));
writeFileSync(process.argv[3], JSON.stringify(results, null, 2));
console.log(
  `Evaluated ${results.length} approved cases in isolated SurveyJS-Core candidate`,
);
