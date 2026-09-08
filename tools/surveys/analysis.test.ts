import { expect, test } from "bun:test";
import { aggregateApprovedSurvey } from "../../packages/surveys/src/analysis";
import fixture from "../../tests/fixtures/surveys/analysis-golden.json";

test("hand-calculated golden distributions, denominators, missing and invalid answers", () => {
  const results = aggregateApprovedSurvey(fixture.definition, fixture.responses);
  const q = Object.fromEntries(results.map((value) => [value.questionId, value]));
  expect(results).toHaveLength(9);
  for (const value of results) {
    expect(value.relevant + value.hidden).toBe(5);
    expect(value.answered + value.unanswered + value.invalid).toBe(value.relevant);
  }
  expect(q.gate.counts.map((x) => [x.value, x.count, x.percentage])).toEqual([["yes", 3, 75], ["no", 1, 25]]);
  expect(q.multi.counts.map((x) => [x.label, x.count, x.percentage])).toEqual([["Alpha", 2, 100], ["Beta", 1, 50]]);
  expect([q.multi.answered, q.multi.unanswered, q.multi.invalid]).toEqual([2, 2, 1]);
  expect([q.nps.answered, q.nps.unanswered, q.nps.invalid]).toEqual([3, 1, 1]);
  expect(q.nps.mean).toBeCloseTo(19 / 3);
  expect(q.nps.nps).toBeCloseTo(100 / 3);
  expect([q.number.sum, q.number.mean, q.number.minimum, q.number.maximum]).toEqual([30, 15, 10, 20]);
  expect(q.number.counts).toEqual([]);
  expect([q.follow.relevant, q.follow.answered, q.follow.unanswered, q.follow.hidden]).toEqual([3, 1, 2, 2]);
  expect([q.conditional.relevant, q.conditional.answered, q.conditional.hidden]).toEqual([2, 1, 3]);
  expect([q.text.answered, q.text.invalid, q.text.unanswered]).toEqual([2, 1, 2]);
  expect([q.date.answered, q.date.invalid, q.date.unanswered]).toEqual([1, 1, 3]);
  expect(q.text.counts).toEqual([]);
  expect(q.date.counts).toEqual([]);
  expect(JSON.stringify(results)).not.toContain("SENSITIVE_");
  expect(JSON.stringify(results)).not.toContain("alien");
  expect(JSON.stringify(results)).not.toContain("not-a-date");
  expect(q.matrix.matrixRows.map((row) => [row.answered, row.unanswered, row.invalid])).toEqual([[2, 2, 1], [1, 3, 1]]);
  expect(q.matrix.matrixRows[0].counts.map((x) => [x.count, x.percentage])).toEqual([[1, 50], [1, 50]]);
  expect(q.matrix.matrixRows[1].counts.map((x) => [x.count, x.percentage])).toEqual([[0, 0], [1, 100]]);
});

test("empty results have author-defined buckets and null statistics/percentages", () => {
  const results = aggregateApprovedSurvey(fixture.definition, []);
  for (const value of results) {
    expect([value.relevant, value.answered, value.hidden, value.invalid]).toEqual([0, 0, 0, 0]);
    expect([value.sum, value.mean, value.minimum, value.maximum, value.nps]).toEqual([null, null, null, null, null]);
    expect(value.counts.every((item) => item.count === 0 && item.percentage === null)).toBe(true);
  }
});

test("scalar choices retain exact type/identity and fractional ratings use scale positions", () => {
  const definition = {pages:[{name:"one",elements:[
    {type:"dropdown",name:"choice",choices:[1, "1", 1.0000000001]},
    {type:"rating",name:"decimal",rateMin:0.1,rateMax:0.3,rateStep:0.1},
  ]}]};
  const [choice, rating] = aggregateApprovedSurvey(definition, [
    {choice:1,decimal:0.1},{choice:"1",decimal:0.2},{choice:1.0000000001,decimal:0.3},
    {decimal:0.30000000000000004},
  ]);
  expect(choice.counts.map((item) => item.count)).toEqual([1, 1, 1]);
  expect(rating.counts.map((item) => [item.value, item.count])).toEqual([[0.1, 1], [0.2, 1], [0.3, 1]]);
  expect(rating.nps).toBeNull();
  expect(rating.invalid).toBe(1);
});

test("unknown answer keys cannot silently enter aggregates", () => {
  expect(() => aggregateApprovedSurvey(fixture.definition, [{unexpected:"private"}])).toThrow("unknown_answer");
});
