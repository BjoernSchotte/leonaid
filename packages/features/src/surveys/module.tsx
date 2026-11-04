import { lazy, Suspense } from "react";

import type { UiModule } from "../modules";

const SurveysPage = lazy(() =>
  import("./surveys").then(({ SurveysPage }) => ({ default: SurveysPage })),
);
const SurveyResponsesPage = lazy(() =>
  import("./survey-responses").then(({ SurveyResponsesPage }) => ({
    default: SurveyResponsesPage,
  })),
);

function loading(text: string) {
  return (
    <div className="action-loading" role="status" aria-live="polite">
      <span aria-hidden="true" />
      <p>{text}</p>
    </div>
  );
}

export const surveysModule: UiModule = {
  id: "surveys",
  label: "Umfragen",
  surfaces: ["web"],
  routes: [
    {
      pattern: /^\/surveys(?:\/(new|[0-9a-f-]{36}))?$/,
      render: (context, match) => (
        <Suspense fallback={loading("Umfragen werden geladen …")}>
          <SurveysPage
            client={context.client}
            identity={context.identity}
            createNew={match[1] === "new"}
            surveyId={match[1] && match[1] !== "new" ? match[1] : undefined}
          />
        </Suspense>
      ),
    },
    {
      pattern: /^\/surveys\/([0-9a-f-]{36})\/responses$/,
      render: (context, match) => (
        <Suspense fallback={loading("Antworten werden geladen …")}>
          <SurveyResponsesPage client={context.client} surveyId={match[1]!} />
        </Suspense>
      ),
    },
  ],
};
