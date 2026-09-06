import { Model } from "survey-core";
import { readFileSync, writeFileSync } from "node:fs";
const fixture = new URL("../../tests/fixtures/surveys/", import.meta.url);
const cases = JSON.parse(
  readFileSync(new URL("validation-cases.json", fixture)),
);
const results = cases.map((item) => {
  const model = new Model(
    JSON.parse(readFileSync(new URL(`${item.fixture}.json`, fixture))),
  );
  model.data = item.answers;
  return {
    name: item.name,
    completeValid: model.validate(),
    visible: model
      .getAllQuestions()
      .filter((q) => q.isVisible && q.page.isVisible)
      .map((q) => q.name),
  };
});
writeFileSync(process.argv[2], JSON.stringify(results, null, 2));
console.log(
  `Executed ${results.length} SurveyJS validation/relevance fixtures`,
);
