import React from "react";
import { renderToString } from "react-dom/server";
import { SurveyRunner } from "../../packages/surveys/src/runner";
import type {
  Participation,
  ParticipationAdapter,
} from "../../packages/surveys/src/contracts";
import { writeFileSync } from "node:fs";

const calls: string[] = [];
const unexpected = async () => {
  calls.push("adapter");
  throw new Error("SSR must not call persistence");
};
const adapter: ParticipationAdapter = {
  start: unexpected,
  restore: unexpected,
  save: unexpected,
  complete: unexpected,
};
const participation: Participation = {
  id: "synthetic-ssr",
  inactivityTimeoutSeconds: 1800,
  version: {
    id: "v1",
    surveyId: "synthetic",
    number: 1,
    rendererVersion: "3.0.3",
    capabilityProfile: "initial-v1",
    publishedAt: "2026-09-06T00:00:00Z",
    definition: {
      pages: [
        {
          name: "page",
          elements: [
            { type: "text", name: "answer", title: "Synthetic SSR question" },
          ],
        },
      ],
    },
  },
  response: {
    participationId: "synthetic-ssr",
    versionId: "v1",
    revision: 1,
    status: "in_progress",
    answers: { answer: "synthetic-private-ssr-marker" },
    currentPage: "page",
    lastAnswerChangedAt: null,
    completedAt: null,
    diagnostics: [],
  },
};
let outcome: Record<string, unknown>;
try {
  const html = renderToString(
    React.createElement(SurveyRunner, { participation, adapter, locale: "en" }),
  );
  outcome = {
    rendered: true,
    bytes: Buffer.byteLength(html),
    questionPresent: html.includes("Synthetic SSR question"),
    privateAnswerPresent: html.includes("synthetic-private-ssr-marker"),
  };
} catch (error) {
  outcome = {
    rendered: false,
    error: error instanceof Error ? error.message : "unknown rendering error",
  };
}
if (calls.length) throw new Error("Unexpected SSR adapter side effect");
outcome.adapterCalls = calls.length;
outcome.strategy =
  "Browser-mounted respondent UI in both hosts; no private response SSR HTML";
writeFileSync(process.argv[2], JSON.stringify(outcome, null, 2));
console.log(JSON.stringify(outcome));
