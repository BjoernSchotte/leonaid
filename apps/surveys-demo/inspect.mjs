import {
  readFileSync,
  realpathSync,
  readdirSync,
  existsSync,
  writeFileSync,
} from "node:fs";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { SurveyAnalytics, englishAnalytics } from "@leonaid/surveys/analytics";
import { aggregateApprovedSurvey } from "@leonaid/surveys/analysis";
const versions = {
  "@leonaid/surveys": "0.0.0",
  "survey-core": "3.0.3",
  "survey-react-ui": "3.0.3",
  react: "19.2.8",
  "react-dom": "19.2.8",
  scheduler: "0.27.0",
};
const inventory = [];
const surveyManifest = JSON.parse(
  readFileSync("node_modules/@leonaid/surveys/package.json", "utf8"),
);
const hostManifest = JSON.parse(readFileSync("package.json", "utf8"));
assert.deepEqual(surveyManifest.peerDependencies, {
  react: "^19.2.8",
  "react-dom": "^19.2.8",
});
for (const name of ["react", "react-dom"]) {
  assert.equal(hostManifest.dependencies[name], versions[name]);
  assert.equal(surveyManifest.dependencies[name], undefined);
}
for (const [name, version] of Object.entries(versions)) {
  const path = `node_modules/${name}`;
  assert(
    realpathSync(path).startsWith("/consumer/"),
    `External workspace resolution: ${name}`,
  );
  const manifest = JSON.parse(readFileSync(`${path}/package.json`, "utf8"));
  assert.equal(manifest.version, version);
  assert.equal(
    manifest.license,
    name === "@leonaid/surveys" ? "UNLICENSED" : "MIT",
  );
  inventory.push({ name, version, license: manifest.license });
}
const installed = readdirSync("node_modules")
  .filter((name) => !name.startsWith("."))
  .flatMap((name) =>
    name.startsWith("@")
      ? readdirSync(`node_modules/${name}`).map((child) => `${name}/${child}`)
      : [name],
  );
assert.deepEqual(installed.sort(), Object.keys(versions).sort());
assert(!existsSync("/workspace") && !existsSync("/package"));
assert(existsSync("node_modules/@leonaid/surveys/THIRD-PARTY-NOTICES.txt"));
assert(existsSync("node_modules/survey-core/fonts/LICENSE.txt"));
const map = JSON.parse(readFileSync("dist/client.js.map", "utf8"));
assert(map.sources.some((source) => source.includes("surveys/src/runner")));
assert(
  !map.sources.some((source) =>
    /surveys\/src\/(editor|conditions|validation-candidate|analysis|analytics|exports)/.test(
      source,
    ),
  ),
  "Authoring or server modules leaked into respondent bundle",
);
const exportMap = JSON.parse(readFileSync("dist/exports.js.map", "utf8"));
assert(
  exportMap.sources.some((source) => source.includes("surveys/src/exports")),
);
assert(
  !exportMap.sources.some((source) =>
    /survey-core|survey-react-ui|surveys\/src\/(runner|editor|analysis|analytics)/.test(
      source,
    ),
  ),
  "Export consumer imported respondent/editor/analysis runtime",
);
assert(
  !/@font-face/.test(readFileSync("dist/client.css", "utf8")),
  "Fontless stylesheet expected",
);
const proof = {
  inventory,
  reactCompatibilityPeers: surveyManifest.peerDependencies,
  exactHostReact: hostManifest.dependencies.react,
  sourceCount: map.sources.length,
  clientBytes: readFileSync("dist/client.js").length,
  tarballBytes: readFileSync("/artifact/surveys.tgz").length,
  workspaceResolution: false,
  editorInRespondentBundle: false,
  analysisInRespondentBundle: false,
  packedAnalysisVerified: true,
  packedAnalyticsVerified: true,
  analyticsInRespondentBundle: false,
  exportsInRespondentBundle: false,
  packedExportsVerified: true,
  exportClientBytes: readFileSync("dist/exports.js").length,
};
const [rating, text] = aggregateApprovedSurvey(
  {
    pages: [
      {
        name: "one",
        elements: [
          { type: "rating", name: "nps", rateMin: 0, rateMax: 10 },
          { type: "comment", name: "comment" },
        ],
      },
    ],
  },
  [{ nps: 10, comment: "PRIVATE_CONSUMER_TEXT" }, { nps: 9 }, { nps: 0 }, {}],
);
assert.equal(rating.answered, 3);
assert.equal(rating.unanswered, 1);
assert(Math.abs(rating.nps - 100 / 3) < 1e-9);
assert.equal(text.answered, 1);
assert.deepEqual(text.counts, []);
assert(!JSON.stringify([rating, text]).includes("PRIVATE_CONSUMER_TEXT"));
const rendered = renderToStaticMarkup(
  createElement(SurveyAnalytics, {
    snapshot: {
      id: "consumer-snapshot",
      surveyId: "consumer",
      createdAt: "2026-09-07T00:00:00Z",
      filter: {
        versionId: "consumer-version",
        statuses: ["partial", "completed"],
        isTest: false,
        createdFrom: null,
        createdBefore: null,
      },
      versionNumber: 1,
      rendererVersion: "3.0.3",
      capabilityProfile: "initial-v1",
      participationCount: 4,
      statusCounts: { in_progress: 2, partial: 3, completed: 1 },
      lastPageCounts: [{ pageId: "one", title: "One", count: 4 }],
      questions: [rating, text],
    },
    messages: {
      ...englishAnalytics,
      heading: "Independent results",
      nps: "Independent NPS",
    },
    locale: "en",
  }),
);
assert(
  rendered.includes("Independent results") &&
    rendered.includes("Independent NPS"),
);
assert(rendered.includes("33.33") && rendered.includes("<table"));
assert(!rendered.includes("PRIVATE_CONSUMER_TEXT"));
assert(existsSync("node_modules/@leonaid/surveys/src/analytics.css"));
writeFileSync("package-proof.json", JSON.stringify(proof, null, 2));
console.log(
  "PASS: packed independent consumer, exact permissive dependencies, font notices and respondent bundle boundary",
);
