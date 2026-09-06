import {
  readFileSync,
  realpathSync,
  readdirSync,
  existsSync,
  writeFileSync,
} from "node:fs";
import assert from "node:assert/strict";
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
    /surveys\/src\/(editor|conditions|validation-candidate|analysis)/.test(source),
  ),
  "Authoring or server modules leaked into respondent bundle",
);
assert(
  !/@font-face/.test(readFileSync("dist/client.css", "utf8")),
  "Fontless stylesheet expected",
);
const proof = {
  inventory,
  sourceCount: map.sources.length,
  clientBytes: readFileSync("dist/client.js").length,
  tarballBytes: readFileSync("/artifact/surveys.tgz").length,
  workspaceResolution: false,
  editorInRespondentBundle: false,
  analysisInRespondentBundle: false,
  packedAnalysisVerified: true,
};
const [rating, text] = aggregateApprovedSurvey({pages:[{name:"one",elements:[
  {type:"rating",name:"nps",rateMin:0,rateMax:10},
  {type:"comment",name:"comment"},
]}]}, [{nps:10,comment:"PRIVATE_CONSUMER_TEXT"},{nps:9},{nps:0},{}]);
assert.equal(rating.answered, 3);
assert.equal(rating.unanswered, 1);
assert(Math.abs(rating.nps - 100 / 3) < 1e-9);
assert.equal(text.answered, 1);
assert.deepEqual(text.counts, []);
assert(!JSON.stringify([rating,text]).includes("PRIVATE_CONSUMER_TEXT"));
writeFileSync("package-proof.json", JSON.stringify(proof, null, 2));
console.log(
  "PASS: packed independent consumer, exact permissive dependencies, font notices and respondent bundle boundary",
);
