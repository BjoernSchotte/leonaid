/**
 * Which values SurveyJS treats as equal in a condition (review 5.6b, N14).
 *
 *   bun tools/surveys/equality-sweep.ts write <fixture.json>
 *   bun tools/surveys/equality-sweep.ts check <fixture.json>
 *
 * Every pair of the corpus goes through the runner's survey-core condition
 * evaluation (ConditionRunner): "{a} = {b}" and "{c} contains {b}" with
 * c = [a], the two forms disclose models. The fixture lists the pairs that
 * either form calls equal; tests/unit/test_survey_disclosure.py asserts
 * that disclose's keys equate them or treat one side as opaque.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { ConditionRunner } from "survey-core";

type Encoded = {
  type: "string" | "number" | "boolean" | "null";
  value: string;
};

const strings = [
  "true",
  "false",
  "True",
  "TRUE",
  "False",
  "",
  " ",
  " ",
  "0x10",
  "0X10",
  "0b1",
  "0o7",
  "1e1",
  "10",
  "16",
  "16.0",
  "+16",
  "-16",
  "007",
  "7",
  "-0",
  "0",
  "1",
  "1.5",
  "Infinity",
  "-Infinity",
  "NaN",
  "null",
  "Null",
  "undefined",
  "x",
  "X",
  "x ",
  " x",
  " x",
  "16 ",
  " 16",
  "16 ",
  "﻿16",
  "Ja",
  "ja",
  "JA",
  "a",
  "A",
  "1,5",
  "-0x10",
];
const numbers = [0, -0, 1, 16, 1.5, 10, 7, -16];
const corpus: unknown[] = [...strings, ...numbers, true, false, null];

function encode(value: unknown): Encoded {
  if (value === null) return { type: "null", value: "null" };
  if (typeof value === "boolean")
    return { type: "boolean", value: String(value) };
  if (typeof value === "number")
    return {
      type: "number",
      value: Object.is(value, -0) ? "-0" : String(value),
    };
  return { type: "string", value: value as string };
}

const equals = new ConditionRunner("{a} = {b}");
const contains = new ConditionRunner("{c} contains {b}");

function sweep() {
  const equal: [number, number][] = [];
  for (let i = 0; i < corpus.length; i++) {
    for (let j = i + 1; j < corpus.length; j++) {
      const [a, b] = [corpus[i], corpus[j]];
      if (
        equals.runValues({ a, b }) ||
        equals.runValues({ a: b, b: a }) ||
        contains.runValues({ c: [a], b }) ||
        contains.runValues({ c: [b], b: a })
      )
        equal.push([i, j]);
    }
  }
  return { corpus: corpus.map(encode), equal };
}

const [mode, path] = process.argv.slice(2);
if (mode === "write" && path) {
  writeFileSync(path, JSON.stringify(sweep(), null, 1) + "\n");
} else if (mode === "check" && path) {
  if (
    JSON.stringify(sweep()) !==
    JSON.stringify(JSON.parse(readFileSync(path, "utf8")))
  ) {
    console.error("equality-sweep: FAILED: fixture differs from SurveyJS");
    process.exit(1);
  }
  console.log("equality-sweep: OK: fixture matches SurveyJS");
} else {
  console.error("usage: equality-sweep.ts write|check <fixture.json>");
  process.exit(2);
}
