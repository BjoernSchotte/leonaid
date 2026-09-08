import {
  createSurveyModel,
  restoreSurveyAnswers,
} from "../../packages/surveys/src/model.ts";
import { readFileSync, writeFileSync } from "node:fs";
const fixture = new URL("../../tests/fixtures/surveys/", import.meta.url);
const cases = JSON.parse(
  readFileSync(new URL("validation-cases.json", fixture)),
);
const results = cases.map((item) => {
  const model = createSurveyModel(
    item.definition ??
      JSON.parse(readFileSync(new URL(`${item.fixture}.json`, fixture))),
  );
  restoreSurveyAnswers(model, item.answers);
  const completeValid = model.validate();
  return {
    name: item.name,
    answers: model.data,
    completeValid,
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
