import { lazy, Suspense } from "react";
import type { UiModule } from "../modules";

const SurveysPage = lazy(() =>
  import("./surveys").then(({ SurveysPage }) => ({ default: SurveysPage })),
);

export const surveysModule: UiModule = {
  id: "surveys",
  area: "work",
  surfaces: ["web"],
  routes: [
    {
      pattern: /^\/admin\/surveys(?:\/(new|[0-9a-f-]{36}))?\/?$/,
      render: (context, match) => (
        <Suspense
          fallback={
            <div className="action-loading" role="status" aria-live="polite">
              <span aria-hidden="true" />
              <p>Umfragen werden geladen …</p>
            </div>
          }
        >
          <SurveysPage
            {...context}
            createNew={match[1] === "new"}
            surveyId={match[1] && match[1] !== "new" ? match[1] : undefined}
          />
        </Suspense>
      ),
    },
  ],
};
