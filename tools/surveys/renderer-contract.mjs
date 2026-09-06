import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { Model } from "survey-core";
const load = (name) =>
  new Model(
    JSON.parse(
      readFileSync(
        new URL(`../../tests/fixtures/surveys/${name}.json`, import.meta.url),
      ),
    ),
  );
const taxi = load("krapfentaxi");
assert.equal(taxi.pages.length, 3);
assert.equal(taxi.getQuestionByName("delivery_feedback").isVisible, false);
taxi.setValue("delivery_rating", 1);
assert.equal(taxi.getQuestionByName("delivery_feedback").isVisible, true);
taxi.setValue("delivery_feedback", "Lieferung später als erwartet");
taxi.setValue("delivery_rating", 5);
assert.equal(taxi.getQuestionByName("delivery_feedback").isVisible, false);
assert.equal(taxi.validate(), false, "missing relevant required answers");
taxi.setValue("freshness", "fresh");
taxi.setValue("nps", 9);
assert.equal(taxi.validate(), true);
const golf = load("golf");
assert.equal(golf.validate(), false);
golf.setValue("event_rating", { organization: 3, course: 2, catering: 3 });
assert.equal(golf.validate(), true);
golf.setValue("improvements", ["food"]);
assert.equal(golf.getQuestionByName("food_feedback").isVisible, true);
golf.setValue("improvements", ["schedule"]);
assert.equal(golf.getQuestionByName("food_feedback").isVisible, false);
golf.setValue("handicap", 100);
assert.equal(golf.validate(), false);
console.log(
  "SurveyJS 3.0.3 fixture semantics: multipage, conditions, required matrix and numeric limits passed.",
);
